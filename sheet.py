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


THAI_MONTHS = {
    "มกราคม": 1,
    "กุมภาพันธ์": 2,
    "มีนาคม": 3,
    "เมษายน": 4,
    "พฤษภาคม": 5,
    "มิถุนายน": 6,
    "กรกฎาคม": 7,
    "สิงหาคม": 8,
    "กันยายน": 9,
    "ตุลาคม": 10,
    "พฤศจิกายน": 11,
    "ธันวาคม": 12,
}


def get_primary_month_from_worksheet():
    for th_name, month_num in THAI_MONTHS.items():
        if th_name in WORKSHEET_NAME:
            return month_num
    raise ValueError("ไม่พบชื่อเดือนภาษาไทยใน WORKSHEET_NAME")


def find_day_column_safe(target_date):
    sheet = get_sheet()
    header = sheet.row_values(HEADER_ROW)

    primary_month = get_primary_month_from_worksheet()
    target_day = target_date.day
    target_month = target_date.month

    matched_columns = []

    for idx, cell in enumerate(header, start=1):
        if not cell:
            continue

        text = str(cell)
        text = re.sub(r"\s+", " ", text).strip()

        # 1️⃣ รูปแบบ วันที่ dd/mm
        m_full = re.search(r"วันที่\s*0*(\d{1,2})\s*/\s*0*(\d{1,2})", text)
        if m_full:
            day = int(m_full.group(1))
            month = int(m_full.group(2))
            if day == target_day and month == target_month:
                matched_columns.append(idx)
            continue

        # 2️⃣ รูปแบบ วันที่ dd (ไม่มีเดือน)
        m_day = re.search(r"วันที่\s*0*(\d{1,2})", text)
        if m_day:
            day = int(m_day.group(1))
            if (
                day == target_day
                and target_month == primary_month
            ):
                matched_columns.append(idx)

    if len(matched_columns) == 1:
        return matched_columns[0]

    if len(matched_columns) == 0:
        raise ValueError(
            f"ไม่พบ column ของวันที่ {target_date.strftime('%d/%m')}"
        )

    raise ValueError(
        f"พบ column ซ้ำของวันที่ {target_date.strftime('%d/%m')} "
        f"({matched_columns}) — ป้องกัน silent corruption"
    )



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

