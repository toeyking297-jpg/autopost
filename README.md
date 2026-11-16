# AutoPost

ระบบโพสต์ออโต้: คิวโพสต์บนหน้าเว็บ (ใช้จากมือถือ) → GitHub Actions โพสต์ให้ตามเวลา
- **Instagram Reels** (แชร์ไปเพจ Facebook อัตโนมัติจากการตั้งค่าใน IG → ยอดวิวรวมกัน)
- **YouTube Shorts**

หน้าแดชบอร์ด: https://toeyking297-jpg.github.io/autopost/

## โครงสร้าง
- `config/accounts.json` บัญชีทั้งหมด (ชื่อ IG, ชื่อ secret ของ YouTube, ช่องเวลาประจำ)
- `queue/queue.json` คิวโพสต์ · `media/` วิดีโอที่รอโพสต์ (ลบเองหลังโพสต์เสร็จ)
- `scripts/post.py` ตัวโพสต์ (รันทุก ~5 นาที) · `scripts/enqueue.py` เพิ่มคิวจากบรรทัดคำสั่ง
- `.github/workflows/post.yml` ตารางรัน · `docs/index.html` แดชบอร์ด

## Secrets ที่ต้องใส่ (Settings → Secrets and variables → Actions)
| ชื่อ | ใช้กับ |
|---|---|
| `META_TOKEN` | Instagram ทุกบัญชี (token ที่ไม่หมดอายุจาก System User ใน Meta Business) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET` | Google Cloud OAuth client (ใช้ร่วมทุกช่อง) |
| `YT_REFRESH_PANICPAL`, `YT_REFRESH_VELYN`, `YT_REFRESH_LOKSON` | refresh token ของแต่ละช่อง YouTube |

กุญแจที่ยังไม่ใส่จะไม่ทำให้คลิปหาย: คลิปจะรออยู่ในคิวจนกว่าจะตั้งค่าเสร็จ
ตรวจว่าตั้งค่าครบไหม: แดชบอร์ด → ⚙︎ → "ตรวจกุญแจ/บัญชี"
