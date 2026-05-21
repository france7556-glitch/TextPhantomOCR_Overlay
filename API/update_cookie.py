import json
import os
import sys
import urllib.request

def _load_dotenv():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths_to_check = [
        os.path.join(current_dir, ".env"),
        os.path.join(os.path.dirname(current_dir), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(current_dir)), ".env")
    ]
    for p in paths_to_check:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

_load_dotenv()

cookie_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookie.json")

print("=" * 50)
print("  เครื่องมืออัพเดท Google Lens Cookie (Local & Firebase)")
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
    print(f"\n✅ บันทึก Cookie ลงในเครื่อง (Local) สำเร็จแล้ว!")
    print(f"   ไฟล์: {cookie_file}")
    print(f"   จำนวน Cookie: {len(cookie_dict)} ตัว")
except Exception as e:
    print(f"\n❌ เกิดข้อผิดพลาดในการบันทึกไฟล์: {e}")

# Firebase Upload Option
print("\n" + "-" * 50)
default_firebase_url = os.getenv(
    "FIREBASE_URL",
    "https://ocrr-d0032-default-rtdb.asia-southeast1.firebasedatabase.app/lens/cookie.json"
).strip()

print(f"ต้องการอัปโหลด Cookie นี้ไปยัง Firebase ของคุณหรือไม่?")
print(f"Firebase URL ปัจจุบัน: {default_firebase_url}")
print("กด Enter เพื่ออัปโหลดไปยัง URL ข้างต้น หรือพิมพ์ URL อื่นที่ต้องการ (หรือพิมพ์ 'n' เพื่อยกเลิก):")
choice = input().strip()

if choice.lower() != 'n':
    firebase_url = default_firebase_url
    if choice and choice.startswith("http"):
        firebase_url = choice
    
    # Ensure path ends with /lens/cookie.json if it's just the root domain
    if "firebasedatabase.app" in firebase_url or "firebaseio.com" in firebase_url:
        if not firebase_url.endswith(".json"):
            firebase_url = firebase_url.rstrip("/") + "/lens/cookie.json"
            
    print(f"\nกำลังอัปโหลดไปยัง Firebase: {firebase_url} ...")
    try:
        req = urllib.request.Request(
            firebase_url,
            data=json.dumps(cookie_dict).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='PUT'
        )
        with urllib.request.urlopen(req) as response:
            if response.getcode() == 200:
                print("✅ อัปโหลดขึ้น Firebase สำเร็จแล้ว!")
                print("ตอนนี้ระบบที่ดึง Cookie จาก Firebase ของคุณจะใช้งานได้ปกติครับ")
            else:
                print(f"❌ อัปโหลดไม่สำเร็จ (Status Code: {response.getcode()})")
    except Exception as ex:
        print(f"❌ เกิดข้อผิดพลาดในการอัปโหลดขึ้น Firebase: {ex}")
else:
    print("\nยกเลิกการอัปโหลดขึ้น Firebase")

input("\nกด Enter เพื่อปิด...")
