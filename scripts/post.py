"""AutoPost: โพสต์คลิปที่ถึงเวลาในคิว ไปที่ Instagram Reels (แชร์ไปเพจ FB อัตโนมัติ) และ YouTube Shorts

รันโดย GitHub Actions ทุก ~5 นาที (.github/workflows/post.yml)
  python scripts/post.py            โพสต์รายการที่ถึงเวลา
  python scripts/post.py --dry-run  ไม่ยิง API จริง แค่บอกว่าจะทำอะไร
  python scripts/post.py --check    ตรวจกุญแจ/บัญชีทั้งหมด (ไม่โพสต์)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUEUE = ROOT / "queue" / "queue.json"
ACCOUNTS = ROOT / "config" / "accounts.json"
TZ = dt.timezone(dt.timedelta(hours=7))
GRAPH_VER = "v22.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VER}"
MAX_ATTEMPTS = 3

SECRETS: dict = {}
try:
    SECRETS = json.loads(os.environ.get("SECRETS_JSON") or "{}") or {}
except json.JSONDecodeError:
    SECRETS = {}


def secret(name: str) -> str:
    return (SECRETS.get(name) or os.environ.get(name) or "").strip()


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def parse_time(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=TZ)


def log(*a):
    print(*a, flush=True)


class PostError(Exception):
    pass


class ConfigError(PostError):
    """กุญแจ/บัญชียังไม่ได้ตั้ง: ไม่นับเป็นการลองโพสต์ (ไม่ลบคลิป รอจนตั้งค่าเสร็จ)"""


# ---------------------------------------------------------------- Instagram
_ig_ids: dict | None = None


def ig_user_ids() -> dict:
    """username -> IG user id ของทุกเพจที่ META_TOKEN เข้าถึงได้"""
    global _ig_ids
    if _ig_ids is not None:
        return _ig_ids
    token = secret("META_TOKEN")
    if not token:
        raise ConfigError("ยังไม่ได้ใส่ secret META_TOKEN")
    out: dict = {}
    url = f"{GRAPH}/me/accounts"
    params = {"fields": "name,instagram_business_account{id,username}", "limit": 100, "access_token": token}
    while url:
        r = requests.get(url, params=params, timeout=60)
        data = r.json()
        if "error" in data:
            # token อาจเป็น page token: ลองถามจากตัวเพจเอง
            r2 = requests.get(f"{GRAPH}/me", params={"fields": "name,instagram_business_account{id,username}", "access_token": token}, timeout=60).json()
            iba = r2.get("instagram_business_account")
            if iba:
                out[iba["username"].lower()] = iba["id"]
                break
            raise ConfigError(f"META_TOKEN ใช้ไม่ได้: {data['error'].get('message')}")
        for page in data.get("data", []):
            iba = page.get("instagram_business_account")
            if iba and iba.get("username"):
                out[iba["username"].lower()] = iba["id"]
        url = data.get("paging", {}).get("next")
        params = None
    _ig_ids = out
    return out


def ig_post(account: dict, video: pathlib.Path, caption: str) -> str:
    token = secret("META_TOKEN")
    username = account["ig"]["username"].lower()
    uid = account["ig"].get("user_id") or ig_user_ids().get(username)
    if not uid:
        raise ConfigError(f"META_TOKEN มองไม่เห็น IG @{username} (เพจต้องเชื่อม IG แบบธุรกิจ และให้สิทธิ์เพจนี้ตอนสร้าง token)")

    # 1) สร้าง container แบบอัปโหลดไฟล์ตรง (ไม่ต้องมีลิงก์สาธารณะ)
    r = requests.post(f"{GRAPH}/{uid}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption,
        "share_to_feed": "true", "access_token": token}, timeout=60).json()
    if "id" not in r:
        raise PostError(f"IG สร้างโพสต์ไม่ได้: {r.get('error', r)}")
    cid = r["id"]

    # 2) อัปโหลดไฟล์วิดีโอ
    size = video.stat().st_size
    with open(video, "rb") as fh:
        up = requests.post(f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VER}/{cid}", headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}, data=fh, timeout=600)
    upj = up.json() if up.content else {}
    if not upj.get("success"):
        raise PostError(f"IG อัปโหลดวิดีโอไม่ผ่าน: {upj or up.text[:300]}")

    # 3) รอ IG ประมวลผล
    for _ in range(60):  # สูงสุด ~10 นาที
        st = requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": token}, timeout=60).json()
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise PostError(f"IG ประมวลผลวิดีโอไม่ผ่าน: {st.get('status')}")
        time.sleep(10)
    else:
        raise PostError("IG ประมวลผลวิดีโอนานเกินไป")

    # 4) เผยแพร่
    pub = requests.post(f"{GRAPH}/{uid}/media_publish", data={"creation_id": cid, "access_token": token}, timeout=120).json()
    if "id" not in pub:
        raise PostError(f"IG เผยแพร่ไม่ได้: {pub.get('error', pub)}")
    link = requests.get(f"{GRAPH}/{pub['id']}", params={"fields": "permalink", "access_token": token}, timeout=60).json()
    return link.get("permalink") or f"ig media {pub['id']}"


# ---------------------------------------------------------------- YouTube
def yt_access_token(refresh_secret: str) -> str:
    cid, csec, rt = secret("YT_CLIENT_ID"), secret("YT_CLIENT_SECRET"), secret(refresh_secret)
    missing = [n for n, v in (("YT_CLIENT_ID", cid), ("YT_CLIENT_SECRET", csec), (refresh_secret, rt)) if not v]
    if missing:
        raise ConfigError("ยังไม่ได้ใส่ secret: " + ", ".join(missing))
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": csec, "refresh_token": rt, "grant_type": "refresh_token"}, timeout=60).json()
    if "access_token" not in r:
        raise ConfigError(f"YouTube ขอสิทธิ์ไม่ผ่าน: {r.get('error_description') or r}")
    return r["access_token"]


def yt_post(account: dict, video: pathlib.Path, title: str, description: str, tags: list[str]) -> str:
    token = yt_access_token(account["youtube"]["refresh_secret"])
    meta = {
        "snippet": {"title": title[:100], "description": description[:5000],
                    "tags": [t.lstrip("#") for t in tags][:15], "categoryId": "24"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    size = video.stat().st_size
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        data=json.dumps(meta), timeout=60)
    loc = init.headers.get("Location")
    if not loc:
        raise PostError(f"YouTube เริ่มอัปโหลดไม่ได้: {init.text[:300]}")
    with open(video, "rb") as fh:
        up = requests.put(loc, headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"}, data=fh, timeout=1800)
    j = up.json() if up.content else {}
    if "id" not in j:
        raise PostError(f"YouTube อัปโหลดไม่ผ่าน: {j.get('error', up.text[:300])}")
    return f"https://youtube.com/shorts/{j['id']}"


# ---------------------------------------------------------------- queue
def load(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def save_queue(q: dict):
    QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_caption(item: dict) -> str:
    tags = " ".join(h if h.startswith("#") else f"#{h}" for h in item.get("hashtags", []))
    cap = (item.get("caption") or "").strip()
    return f"{cap}\n\n{tags}".strip() if tags else cap


def process(item: dict, accounts: dict, dry: bool) -> bool:
    """คืน True ถ้ามีการเปลี่ยนแปลง"""
    acc = accounts.get(item["account"])
    res = item.setdefault("results", {})
    if not acc:
        item["status"] = "error"
        item["error"] = f"ไม่รู้จักบัญชี {item['account']}"
        return True
    video = ROOT / item["video"]
    if not video.exists():
        item["status"] = "error"
        item["error"] = f"ไม่พบไฟล์วิดีโอ {item['video']}"
        return True

    caption = build_caption(item)
    for plat in item.get("platforms", []):
        r = res.setdefault(plat, {"status": "pending", "attempts": 0})
        if r["status"] == "done" or r["attempts"] >= MAX_ATTEMPTS:
            continue
        if plat == "ig" and not acc.get("ig"):
            r.update(status="error", error="บัญชีนี้ไม่มี IG", attempts=MAX_ATTEMPTS)
            continue
        if plat == "youtube" and not acc.get("youtube"):
            r.update(status="error", error="บัญชีนี้ไม่มี YouTube", attempts=MAX_ATTEMPTS)
            continue
        log(f"→ {item['id']} [{acc['name']}] {plat}")
        if dry:
            log(f"   (dry-run) จะโพสต์ {video.name} ({video.stat().st_size // 1024} KB)")
            continue
        r["attempts"] += 1
        try:
            if plat == "ig":
                url = ig_post(acc, video, caption)
            elif plat == "youtube":
                title = item.get("title") or (item.get("caption") or "").split("\n")[0][:90] or acc["name"]
                url = yt_post(acc, video, title, caption, item.get("hashtags", []))
            else:
                raise PostError(f"ไม่รู้จักแพลตฟอร์ม {plat}")
            r.update(status="done", url=url, at=now().isoformat(timespec="seconds"))
            r.pop("error", None)
            log(f"   ✓ {url}")
        except ConfigError as e:
            r["attempts"] -= 1  # ยังไม่นับ รอตั้งค่าให้เสร็จ
            r.update(status="error", error=str(e)[:500])
            log(f"   ⚙ {e}")
            continue
        except Exception as e:  # noqa: BLE001
            r.update(status="error", error=str(e)[:500])
            log(f"   ✗ {e}")

    if dry:
        return False
    states = [res[p]["status"] for p in item.get("platforms", [])]
    retry_left = any(res[p]["status"] != "done" and res[p]["attempts"] < MAX_ATTEMPTS for p in item.get("platforms", []))
    if all(s == "done" for s in states):
        item["status"] = "done"
    elif retry_left:
        item["status"] = "retry"
    elif any(s == "done" for s in states):
        item["status"] = "partial"
    else:
        item["status"] = "error"
    if item["status"] in ("done", "partial", "error") and video.exists():
        video.unlink()  # ลบไฟล์หลังโพสต์เสร็จ ไม่ให้ repo บวม
        item["video_removed"] = True
    return True


def main():
    dry = "--dry-run" in sys.argv
    accounts = {a["key"]: a for a in load(ACCOUNTS)["accounts"]}

    if "--check" in sys.argv:
        ok = True
        try:
            ids = ig_user_ids()
            log("IG ที่ META_TOKEN มองเห็น:", ", ".join(f"@{k}" for k in ids) or "(ไม่มี)")
            for a in accounts.values():
                if a.get("ig"):
                    u = a["ig"]["username"].lower()
                    log(f"  {a['name']}: @{u} {'✓' if u in ids else '✗ ไม่เจอ'}")
                    ok &= u in ids
        except PostError as e:
            log("IG:", e)
            ok = False
        for a in accounts.values():
            if a.get("youtube"):
                try:
                    yt_access_token(a["youtube"]["refresh_secret"])
                    log(f"  YouTube {a['name']}: ✓")
                except PostError as e:
                    log(f"  YouTube {a['name']}: ✗ {e}")
                    ok = False
        sys.exit(0 if ok else 1)

    q = load(QUEUE)
    changed = False
    t = now()
    due = [i for i in q["items"] if i.get("status", "pending") in ("pending", "retry") and parse_time(i["schedule_at"]) <= t]
    due.sort(key=lambda i: i["schedule_at"])
    log(f"{t:%Y-%m-%d %H:%M} · ถึงเวลาโพสต์ {len(due)} รายการ")
    for item in due:
        changed |= process(item, accounts, dry)
        if changed:
            save_queue(q)  # บันทึกทุกรายการ กันโพสต์ซ้ำถ้างานถูกตัดกลางทาง
    if not due:
        log("ไม่มีอะไรต้องโพสต์")


if __name__ == "__main__":
    main()
