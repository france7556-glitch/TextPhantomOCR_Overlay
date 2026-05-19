import json
import os
import sys

cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookie.json")

print("=" * 50)
print("  เครื่องมืออัพเดท Google Lens Cookie (Local)")
print("=" * 50)
print()
print("วิธีเอา Cookie จาก Google Lens:")
print("  1. เปิดเบราว์เซอร์ไปที่ https://lens.google.com")
print("     (แนะนำให้ล็อกอิน Google Account สำรองไว้ก่อน)")
print("  2. กด F12 เพื่อเปิด Developer Tools")
print("  3. ไปที่แถบ 'Network'")
print("  4. กด F5 เพื่อรีเฟรชหน้าเว็บ")
print("  5. คลิกที่รายการแรกสุดในลิสต์ (เช่น lens.google.com หรือ ?olud)")
print("  6. ในหน้าต่างด้านขวา เลือกแท็บ 'Headers'")
print("  7. เลื่อนลงไปหา 'Request Headers'")
print("  8. หาบรรทัดที่เขียนว่า 'cookie:'")
print("  9. คลิกขวาที่ค่าของมัน แล้วเลือก 'Copy value'")
print()
print("-" * 50)
print("วาง Cookie ที่ก็อปปี้มาลงที่นี่ (แล้วกด Enter):")
cookie_string = input().strip()

if not cookie_string:
    print("\n❌ ข้อผิดพลาด: ไม่พบ Cookie")
    input("กด Enter เพื่อปิด...")
    sys.exit(1)

# Parse cookie string into a dictionary
cookie_dict = {}
for item in cookie_string.split(';'):
    if '=' in item:
        key, value = item.split('=', 1)
        cookie_dict[key.strip()] = value.strip()

if not cookie_dict:
    print("\n❌ ข้อผิดพลาด: รูปแบบ Cookie ไม่ถูกต้อง")
    input("กด Enter เพื่อปิด...")
    sys.exit(1)

print(f"\nกำลังบันทึก Cookie ({len(cookie_dict)} ตัว) ลงไฟล์ {cookie_file} ...")

try:
    with open(cookie_file, "w", encoding="utf-8") as f:
        json.dump(cookie_dict, f, indent=2, ensure_ascii=False)
    print(f"\n✅ บันทึก Cookie สำเร็จแล้ว!")
    print(f"   ไฟล์: {cookie_file}")
    print(f"   จำนวน Cookie: {len(cookie_dict)} ตัว")
    print(f"\n   ตอนนี้ระบบ OCR จะกลับมาใช้งานได้ปกติครับ")
    print(f"   (Cookie ถูกเก็บไว้ในเครื่องคอมพิวเตอร์ของคุณเท่านั้น ไม่ถูกส่งขึ้นอินเทอร์เน็ต)")
except Exception as e:
    print(f"\n❌ เกิดข้อผิดพลาด: {e}")

input("\nกด Enter เพื่อปิด...")
