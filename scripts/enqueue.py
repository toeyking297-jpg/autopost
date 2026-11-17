"""เพิ่มคลิปเข้าคิวจากบรรทัดคำสั่ง (ใช้ตอน Claude ทำคลิปเสร็จแล้วส่งเข้าคิวเอง)

python scripts/enqueue.py --account doopleon --video clip.mp4 --at "2026-11-17 07:00" \
    --caption "..." --tags "#a #b #c #d #e" [--platforms ig,youtube] [--title "..."]
--at ใส่ "next" = ช่องเวลาว่างถัดไปของบัญชีนั้น (ตาม slots ใน config/accounts.json)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import secrets
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUEUE = ROOT / "queue" / "queue.json"
ACCOUNTS = ROOT / "config" / "accounts.json"
TZ = dt.timezone(dt.timedelta(hours=7))


def next_slot(acc: dict, taken: set[str]) -> dt.datetime:
    slots = acc.get("slots") or ["07:00", "11:45", "17:45"]
    day = dt.datetime.now(TZ).replace(second=0, microsecond=0)
    for d in range(0, 60):
        base = day + dt.timedelta(days=d)
        for s in sorted(slots):
            h, m = map(int, s.split(":"))
            t = base.replace(hour=h, minute=m)
            if t > dt.datetime.now(TZ) and t.isoformat() not in taken:
                return t
    raise SystemExit("หาช่องเวลาว่างไม่เจอ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--at", default="next")
    ap.add_argument("--caption", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--platforms", default="")
    ap.add_argument("--cover-sec", type=float, default=None, help="เฟรมที่ใช้เป็นปก (วินาที)")
    ap.add_argument("--not-ai", action="store_true")
    a = ap.parse_args()

    accounts = {x["key"]: x for x in json.loads(ACCOUNTS.read_text(encoding="utf-8"))["accounts"]}
    acc = accounts.get(a.account) or exit(f"ไม่รู้จักบัญชี {a.account}: {', '.join(accounts)}")
    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    taken = {i["schedule_at"] for i in q["items"] if i["account"] == a.account and i.get("status") in ("pending", "retry")}

    when = next_slot(acc, taken) if a.at == "next" else dt.datetime.fromisoformat(a.at).replace(tzinfo=TZ)
    tags = [t if t.startswith("#") else f"#{t}" for t in a.tags.replace(",", " ").split()]
    if len(tags) != 5:
        print(f"⚠ แฮชแท็กมี {len(tags)} อัน (มาตรฐานคือ 5)")
    plats = [p for p in a.platforms.split(",") if p] or [p for p in ("ig", "youtube") if acc.get(p)]

    pid = when.strftime("%Y%m%d-%H%M") + "-" + a.account + "-" + secrets.token_hex(2)
    dest = ROOT / "media" / f"{pid}.mp4"
    dest.parent.mkdir(exist_ok=True)
    shutil.copyfile(a.video, dest)
    q["items"].append({
        "id": pid, "account": a.account, "platforms": plats, "video": f"media/{pid}.mp4",
        "caption": a.caption, "hashtags": tags, "title": a.title, "ai": not a.not_ai,
        "cover": ({"type": "frame", "offset_ms": int(a.cover_sec * 1000)} if a.cover_sec is not None else None),
        "schedule_at": when.isoformat(timespec="minutes"), "status": "pending",
        "created_at": dt.datetime.now(TZ).isoformat(timespec="seconds"),
    })
    QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"เข้าคิวแล้ว: {pid} → {acc['name']} {', '.join(plats)} เวลา {when:%d/%m %H:%M}")


if __name__ == "__main__":
    main()
