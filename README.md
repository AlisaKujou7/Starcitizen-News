# บอทแจ้งเตือน Star Citizen บน Discord

แจ้งข่าว Comm-Link ใหม่และประกาศสถานะเซิร์ฟเวอร์ RSI เข้าห้อง Discord รันบน GitHub Actions ทุก 30 นาที โดยไม่ต้องมีเซิร์ฟเวอร์

## แหล่งข้อมูล

| ฟีด | แหล่ง | ตรวจของใหม่จาก |
|---|---|---|
| `sc_commlink` | Star Citizen Wiki API | `id` |
| `sc_status` | RSS ของ RSI Status | `guid` |

ทั้งสองแหล่งเป็นข้อมูลสาธารณะ ไม่ต้องล็อกอินหรือใช้ API key

## ติดตั้ง

1. สร้างห้อง `#star-citizen` ใน Discord แล้วสร้าง webhook ของห้องนั้น
2. สร้าง repo บน GitHub แบบ public แล้วอัปโหลดไฟล์ทั้งหมด
3. ไปที่ Settings → Secrets and variables → Actions แล้วเพิ่ม secret ชื่อ `SC_WEBHOOK` เป็น URL ของ webhook
4. ไปที่แท็บ Actions เลือก `notify` แล้วกด Run workflow รอบแรกจะบันทึก `state.json` อย่างเดียว ไม่ส่งข้อความ
5. รอรอบถัดไป เมื่อมีข่าวใหม่บอทจะส่งเข้าห้องเอง

## การตั้งค่า

แก้ที่ `config.yaml`

- `feeds.<ชื่อฟีด>.enabled`: เปิดหรือปิดฟีด
- `batch_threshold`: ถ้ามีของใหม่เกินจำนวนนี้ในรอบเดียว จะรวมเป็นข้อความเดียว
- `role_mention`: ใส่ เช่น `<@&ROLE_ID>` เพื่อแจ้งเตือนเฉพาะคนที่มี role นั้น
- `sources`: URL ของแหล่งข้อมูล

## ทดสอบในเครื่อง

ต้องใช้ Python 3.12

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

พิมพ์ข้อความออกหน้าจอโดยไม่ส่ง Discord และไม่เขียน `state.json`:

```bash
python -m bot.main --dry-run
```

รันเทสต์ที่ไม่ต้องใช้เน็ต:

```bash
python -m pytest -m "not live"
```

## เมื่อมีปัญหา

- **ฟีดดึงไม่ได้:** บอทข้ามฟีดนั้น workflow ยังเขียว ดูคำเตือนในหน้า Actions และดูเวลาที่เริ่มพังจาก `failing_since` ใน `state.json`
- **ส่ง Discord ไม่ได้:** รายการนั้นจะยังไม่ถูกบันทึก และบอทจะลองใหม่รอบถัดไป
- **`state.json` เสีย:** workflow จะเป็นสีแดงและไม่ส่งอะไร ต้องแก้ไฟล์เอง บอทจะไม่รีเซ็ตให้ เพราะจะทำให้ประวัติหาย
- **ต้องการแจ้งรายการเดิมอีกครั้ง:** ลบ ID นั้นออกจาก `seen` ใน `state.json`

## ข้อจำกัด

- GitHub อาจเริ่ม schedule ช้ากว่าเวลาที่ตั้งไว้ โดยเฉพาะช่วงที่ระบบมีงานมาก
- บอทแจ้งเหตุการณ์ RSI ครั้งเดียวต่อ `guid` จึงไม่แจ้งซ้ำเมื่อสถานะเปลี่ยนเป็น Resolved
- GitHub ปิด schedule ของ repo public ที่เงียบเกิน 60 วัน บอทจึงสร้าง keepalive commit เมื่อไม่มี commit เกิน 50 วัน
