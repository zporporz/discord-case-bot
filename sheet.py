import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# ======================
# CONFIG
# ======================
SHEET_NAME = "GloriousTown Police-ข้อมูล"
WORKSHEET_NAME = "เวลาและเคส มกราคม 69"

# column ที่เป็นชื่อ (จากภาพคือคอลัมน์ B)
NAME_COLUMN = 2
HEADER_ROW = 4   # แถวที่มีหัววันที่ (18, 19, 20, ...)


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ======================
# INTERNAL
# ======================
_sheet_cache = None


def get_sheet():
    global _sheet_cache

    if _sheet_cache:
        return _sheet_cache

    creds = Credentials.from_service_account_file(
        "google-service-account.json",
        scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    _sheet_cache = gc.open(SHEET_NAME).worksheet(WORKSHEET_NAME)

    return _sheet_cache


def find_row_by_name(name: str):
    sheet = get_sheet()
    names = sheet.col_values(NAME_COLUMN)

    for idx, cell in enumerate(names, start=1):
        if cell.strip().lower() == name.strip().lower():
            return idx

    return None

def find_day_column(day: int):
    sheet = get_sheet()
    header = sheet.row_values(HEADER_ROW)

    for idx, cell in enumerate(header):
        if cell and str(day) in cell:
            # +1 เพราะ Google Sheet นับ column จาก 1
            return idx + 1

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

if __name__ == "__main__":
    row = find_row_by_name("Lion Kuryu")
    print("ROW =", row)

