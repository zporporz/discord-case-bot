import gspread
import os
import json
import re
from google.oauth2.service_account import Credentials

# ======================
# CONFIG
# ======================
SHEET_NAME = "GloriousTown Police-ลงข้อมูล"
WORKSHEET_NAME = "เวลาและเคส มกราคม 69"

NAME_COLUMN = 2
HEADER_ROW = 4

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

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

    for idx, cell in enumerate(header):
        if not cell:
            continue

        numbers = re.findall(r"\d+", str(cell))
        if numbers and int(numbers[0]) == day:
            return idx + 1

    raise ValueError(f"ไม่พบ column ของวันที่ {day}")


def build_name_row_map(sheet):
    names = sheet.col_values(NAME_COLUMN)  # READ ครั้งเดียว
    mapping = {}

    for idx, cell in enumerate(names, start=1):
        norm = normalize_name(cell)
        if norm:
            mapping[norm] = idx

    return mapping
