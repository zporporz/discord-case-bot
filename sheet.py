import gspread
import os
import json
import re
from google.oauth2.service_account import Credentials

# ======================
# CONFIG
# ======================
SHEET_NAME = "GloriousTown Police-ลงข้อมูล"
WORKSHEET_NAME = "เวลาและเคส กุมภาพันธ์ 69"

NAME_COLUMN = 2
HEADER_ROW = 4

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
# ======================
# BODY CASE CONFIG
# ======================
BODY_WORKSHEET_NAME = "รายชื่อร่วมเคสอุ้ม กุมภาพันธ์ 69"
BODY_HEADER_ROW = 5   # แถววันที่
BODY_TOTAL_ROW = 6    # แถวรวมเคสอุ้ม/ชุบ

# ======================
# INTERNAL
# ======================

def get_sheet():
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set")

    creds_info = json.loads(sa_json)
    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=SCOPES
    )

    gc = gspread.authorize(creds)
    return gc.open(SHEET_NAME).worksheet(WORKSHEET_NAME)


def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r"\+?\d+\s*", "", name)
    name = re.sub(r"\[.*?\]\s*", "", name)
    return name.strip().lower()


def find_day_column(day: int):
    sheet = get_sheet()
    header = sheet.row_values(HEADER_ROW)

    target_day = int(day)

    for idx, cell in enumerate(header, start=1):
        if not cell:
            continue

        text = str(cell)
        text = re.sub(r"\s+", " ", text)  # บีบ whitespace
        text = text.strip()

        # รองรับ: วันที่1, วันที่ 01, วันที่   1, วันที่ 1 (เสาร์)
        m = re.search(r"วันที่\s*0*(\d{1,2})", text)
        if not m:
            continue

        if int(m.group(1)) == target_day:
            return idx

    raise ValueError(f"ไม่พบ column ของวันที่ {day}")


def build_name_row_map(sheet):
    names = sheet.col_values(NAME_COLUMN)  # READ ครั้งเดียว
    mapping = {}

    for idx, cell in enumerate(names, start=1):
        norm = normalize_name(cell)
        if norm:
            mapping[norm] = idx

    return mapping

def get_body_sheet():
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set")

    creds_info = json.loads(sa_json)
    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=SCOPES
    )

    gc = gspread.authorize(creds)
    return gc.open(SHEET_NAME).worksheet(BODY_WORKSHEET_NAME)

def find_body_day_column(work_date):
    """
    หา column จากวันที่ เช่น 22/01
    """
    sheet = get_body_sheet()
    header = sheet.row_values(BODY_HEADER_ROW)

    target = work_date.strftime("%d/%m")

    for idx, cell in enumerate(header, start=1):
        if cell.strip() == target:
            return idx

    raise ValueError(f"ไม่พบ column ของวันที่ {target} ใน Body Case Sheet")

def write_body_case_total(work_date, total):
    sheet = get_body_sheet()
    col = find_body_day_column(work_date)

    sheet.update_cell(BODY_TOTAL_ROW, col, total)

    print(
        f"🧾 Body Case Sheet updated | "
        f"date={work_date} col={col} total={total}"
    )

