"""รวมผลการโพสต์ (คิวของรอบนี้) เข้ากับคิวล่าสุดบน GitHub โดยไม่ทับรายการที่เพิ่ง
เพิ่ม/ลบจากแดชบอร์ดระหว่างที่กำลังโพสต์

python scripts/merge_queue.py /tmp/mine.json
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUEUE = ROOT / "queue" / "queue.json"
FIELDS = ("status", "results", "error", "video_removed")

mine = {i["id"]: i for i in json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["items"]}
q = json.loads(QUEUE.read_text(encoding="utf-8"))
for item in q["items"]:
    m = mine.get(item["id"])
    if not m:
        continue
    for f in FIELDS:
        if f in m:
            item[f] = m[f]
    if m.get("video_removed"):
        (ROOT / item["video"]).unlink(missing_ok=True)
        if (item.get("cover") or {}).get("image"):
            (ROOT / item["cover"]["image"]).unlink(missing_ok=True)
QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
