import gspread
import os
import json
import re
from google.oauth2.service_account import Credentials
from datetime import datetime

# ======================
# CONFIG
# ======================
SHEET_NAME = "GloriousTown Police-ลงข้อมูล"
WORKSHEET_NAME = "เวลาและเคส มกราคม 69"

# column ที่เป็นชื่อ (จากภาพคือคอลัมน์ B)
NAME_COLUMN = 2
HEADER_ROW = 4   # แถวที่มีหัววันที่ (18, 19, 20, ...)


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# ======================
# INTERNAL
# ======================
_sheet_cache = None


def get_sheet():
    global _sheet_cache
    if _sheet_cache:
        return _sheet_cache

    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set")

    creds_info = json.loads(sa_json)

    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=SCOPES
    )

    gc = gspread.authorize(creds)
    _sheet_cache = gc.open(SHEET_NAME).worksheet(WORKSHEET_NAME)
    return _sheet_cache

def normalize_sheet_name(name: str) -> str:
    if not name:
        return ""
    # ลบ +001, 001, ตัวเลขนำหน้า
    name = re.sub(r"^\+?\d+\s*", "", name)
    # ลบ [GRPL], [xxx]
    name = re.sub(r"\[.*?\]\s*", "", name)
    # ลบช่องว่างซ้ำ
    name = re.sub(r"\s+", " ", name)
    return name.strip().lower()


def find_row_by_name(name: str):
    sheet = get_sheet()
    names = sheet.col_values(NAME_COLUMN)

    target = normalize_sheet_name(name)

    for idx, cell in enumerate(names, start=1):
        if normalize_sheet_name(cell) == target:
            return idx

    return None



def find_day_column(day: int):
    sheet = get_sheet()
    header = sheet.row_values(HEADER_ROW)

    for idx, cell in enumerate(header):
        if not cell:
            continue

        # ดึงเลขวันออกมาจาก cell
        numbers = re.findall(r"\d+", str(cell))
        if numbers and int(numbers[0]) == day:
            return idx + 1  # Google Sheet column เริ่มที่ 1

    raise ValueError(f"ไม่พบ column ของวันที่ {day}")


# ======================
# PUBLIC API (เรียกจาก bot)
# ======================
def write_daily_hours(
    officer_name: str,
    hours_text: str,
    date: datetime
):
    day = date.day

    try:
        col = find_day_column(day)
    except ValueError as e:
        print(e)
        return False

    sheet = get_sheet()
    row = find_row_by_name(officer_name)

    if not row:
        print(f"❌ Officer not found in sheet: {officer_name}")
        return False

    from gspread.utils import rowcol_to_a1
    cell = rowcol_to_a1(row, col)

    sheet.update(cell, hours_text)

    print(f"✅ Sheet updated {cell} = {hours_text}")
    return True


