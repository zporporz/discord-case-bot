import gspread
import os
import json
import re
from google.oauth2.service_account import Credentials

# ======================
# CONFIG
# ======================
SHEET_NAME = "GloriousTown Police-ลงข้อมูล"

# ❌ ไม่ต้องแก้ทุกเดือนแล้ว
# WORKSHEET_NAME = "เวลาและเคส กุมภาพันธ์ 69"

NAME_COLUMN = 2
HEADER_ROW = 4

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# ======================
# BODY CASE CONFIG
# ======================
# ❌ ไม่ต้องแก้ทุกเดือนแล้ว
# BODY_WORKSHEET_NAME = "รายชื่อร่วมเคสอุ้ม กุมภาพันธ์ 69"

BODY_HEADER_ROW = 5   # แถววันที่ (01/04)
BODY_TOTAL_ROW = 6    # แถวรวมเคสอุ้ม/ชุบ

THAI_MONTHS = {
    1: "มกราคม",
    2: "กุมภาพันธ์",
    3: "มีนาคม",
    4: "เมษายน",
    5: "พฤษภาคม",
    6: "มิถุนายน",
    7: "กรกฎาคม",
    8: "สิงหาคม",
    9: "กันยายน",
    10: "ตุลาคม",
    11: "พฤศจิกายน",
    12: "ธันวาคม",
}

# ======================
# CORE: AUTH
# ======================
def get_spreadsheet():
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set")

    creds_info = json.loads(sa_json)
    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=SCOPES
    )

    gc = gspread.authorize(creds)
    return gc.open(SHEET_NAME)

# ======================
# AUTO SELECT MAIN WORKSHEET (เวลาและเคส)
# ======================
def get_sheet_by_date(target_date):
    ss = get_spreadsheet()
    month_th = THAI_MONTHS[target_date.month]

    for ws in ss.worksheets():
        title = ws.title.strip()
        if "เวลาและเคส" in title and month_th in title:
            return ws

    raise ValueError(
        f"ไม่พบ worksheet ของเดือน {month_th} (เวลาและเคส)"
    )

# ใช้แทน get_sheet() เดิม (กันพังของโค้ดเก่า)
def get_sheet():
    from datetime import datetime
    return get_sheet_by_date(datetime.now())

# ======================
# NAME NORMALIZE (เหมือนเดิม 100%)
# ======================
def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = re.sub(r"\+?\d+\s*", "", name)
    name = re.sub(r"\[.*?\]\s*", "", name)
    return name.strip().lower()

# ======================
# SAFE DAY COLUMN (ของเดิมมึง ใช้ได้ต่อ)
# ======================
def find_day_column_safe(target_date):
    sheet = get_sheet_by_date(target_date)
    header = sheet.row_values(HEADER_ROW)

    target_day = target_date.day
    target_month = target_date.month

    full_matches = []  # สำหรับ 01/04
    day_only_matches = []  # สำหรับ วันที่ 1

    for idx, cell in enumerate(header, start=1):
        if not cell:
            continue

        text = str(cell)
        text = re.sub(r"\s+", " ", text).strip()

        # ===== Phase 1: จับแบบ วันที่ dd/mm (แม่นที่สุด) =====
        m_full = re.search(r"วันที่\s*0*(\d{1,2})\s*/\s*0*(\d{1,2})", text)
        if m_full:
            day = int(m_full.group(1))
            month = int(m_full.group(2))

            if day == target_day and month == target_month:
                full_matches.append(idx)
            continue  # สำคัญมาก: ไม่ให้ไปติด day-only ซ้ำ

        # ===== Phase 2: จับแบบ วันที่ dd (ใช้เมื่อไม่มี dd/mm) =====
        m_day = re.search(r"วันที่\s*0*(\d{1,2})$", text)
        if m_day:
            day = int(m_day.group(1))
            if day == target_day:
                day_only_matches.append(idx)

    # 🔥 Priority: ใช้ dd/mm ก่อนเสมอ
    if full_matches:
        if len(full_matches) == 1:
            return full_matches[0]
        raise ValueError(
            f"พบ column dd/mm ซ้ำของวันที่ {target_date.strftime('%d/%m')} "
            f"{full_matches}"
        )

    # ถ้าไม่มี dd/mm ค่อยใช้ day-only
    if len(day_only_matches) == 1:
        return day_only_matches[0]

    if len(day_only_matches) == 0:
        raise ValueError(
            f"ไม่พบ column ของวันที่ {target_date.strftime('%d/%m')}"
        )

    raise ValueError(
        f"พบ column 'วันที่ {target_day}' ซ้ำ {day_only_matches} "
        f"— เสี่ยงเขียนผิดช่อง"
    )

# ======================
# BODY SHEET (AUTO MONTH) 🔥
# ======================
def get_body_sheet_by_date(work_date):
    ss = get_spreadsheet()
    month_th = THAI_MONTHS[work_date.month]

    for ws in ss.worksheets():
        title = ws.title.strip()
        if "รายชื่อร่วมเคสอุ้ม" in title and month_th in title:
            return ws

    raise ValueError(
        f"ไม่พบ Body worksheet ของเดือน {month_th}"
    )

# ======================
# BODY COLUMN (ใช้ 01/04 ล้วน = PERFECT)
# ======================
def find_body_day_column(work_date):
    """
    หา column จาก format 01/04 (ตามที่มึงใช้จริง)
    """
    sheet = get_body_sheet_by_date(work_date)
    header = sheet.row_values(BODY_HEADER_ROW)

    target = work_date.strftime("%d/%m")  # เช่น 01/04

    for idx, cell in enumerate(header, start=1):
        if cell and cell.strip() == target:
            return idx

    raise ValueError(
        f"ไม่พบ column ของวันที่ {target} ใน Body Case Sheet"
    )

# ======================
# WRITE BODY TOTAL (ไม่เปลี่ยน logic เดิม)
# ======================
def write_body_case_total(work_date, total):
    sheet = get_body_sheet_by_date(work_date)
    col = find_body_day_column(work_date)

    sheet.update_cell(BODY_TOTAL_ROW, col, total)

    print(
        f"🧾 Body Case Sheet updated | "
        f"date={work_date} col={col} total={total}"
    )

# ======================
# NAME MAP (เหมือนเดิม)
# ======================
def build_name_row_map(sheet):
    names = sheet.col_values(NAME_COLUMN)
    mapping = {}

    for idx, cell in enumerate(names, start=1):
        norm = normalize_name(cell)
        if norm:
            mapping[norm] = idx

    return mapping