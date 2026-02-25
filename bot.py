# ======================
# IMPORTS
# ======================
import os
import re
import discord
import time
import psycopg2
from datetime import datetime, timedelta
from discord.ext import commands
from audit.audit_commands import setup_audit_commands
from discord import Embed
from datetime import timezone
import asyncio
import random
import requests

from sheet import (
    get_sheet,
    get_sheet_by_date,
    find_day_column_safe,
    write_body_case_total,
    build_name_row_map
)

# ======================

SYSTEM_FOOTER = "Created by Lion Kuryu • Police Case Management System"
EMERGENCY_REBUILD_ENABLED = False

ALLOWED_COMMAND_CHANNELS = {
    1449425399397482789,  # ห้องคำสั่งหลัก
    1450143956519227473,   # ห้อง audit
    1450364332784353281
}
DASHBOARD_CHANNEL_ID = 1450794312026685573
DASHBOARD_REACTIONS = [
    "📊", "🚨", "👮", "✅", "🔄",
    "📈", "🕒", "🛡️", "⚡", "📌",
    "🔥", "💥", "📣", "🧠", "👀",
    "🏆", "🥇", "🥈", "🥉", "🎖️"
]

SHEET_SYNC_REPORT_CHANNEL_ID = 1393544204960927764

BODY_CHUB_CHANNEL_ID = 1462829757099151524      # อุ้มอำพราง / ช่วยอุ้มศพ
BODY_WRAP_CHANNEL_ID = 1462829791605559367      # ช่วยห่ออุ้มศพ

BODY_DASHBOARD_CHANNEL_ID = 1450364332784353281

# ======================
# ENV / CONSTANTS
# ======================
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

PBT_ROLE_ID = 1393537553264545922   # 👮 ผบตร.
RESET_PASSWORD = "GRPL2025"         # 🔐 รหัสยืนยัน resetdb

CASE10_CHANNEL_ID = 1443212808316780654
NORMAL_CHANNEL_IDS = [
    1393542799617691658,
    1400477664900288576
]
DAILY_REPORT_CHANNEL_ID = 1449425399397482789  # ห้องรายงาน

TH_TZ = timezone(timedelta(hours=7))

# ======================
# PERMISSION CHECK
# ======================
def is_pbt():
    async def predicate(ctx):
        return any(role.id == PBT_ROLE_ID for role in ctx.author.roles)
    return commands.check(predicate)

# ======================
# DB HELPERS
# ======================

def send_email_alert(subject, body):
    api_key = os.getenv("RESEND_API_KEY")
    to_email = os.getenv("ALERT_EMAIL_TO")
    from_email = os.getenv("ALERT_EMAIL_FROM")

    if not api_key or not to_email or not from_email:
        print("⚠️ Resend ENV not set, skip email alert")
        return

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_email,  # เช่น oncall@resend.dev
                "to": [to_email],
                "subject": subject,
                "text": body,
            },
            timeout=10,
        )

        if 200 <= response.status_code < 300:
            print("📧 Resend email sent successfully")
        else:
            print("❌ Resend email failed:", response.text)

    except Exception as e:
        print("❌ Resend exception:", e)


def get_conn(retries=3, delay=2):
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")

    for attempt in range(retries):
        try:
            return psycopg2.connect(
                DATABASE_URL,
                connect_timeout=10,
                sslmode="require",
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5
            )
        except psycopg2.OperationalError as e:
            print(f"⚠️ DB connect failed (attempt {attempt+1}/{retries}):", e)
            time.sleep(delay)

    raise RuntimeError("❌ Database connection failed after retries")

def save_case_pg(
    name: str,
    channel: str,
    case_type: str,
    cases: int,
    message_id: int,
    message_date,
    is_uphill: bool = False
):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO cases
                     (date, name, channel, case_type, cases, message_id, is_uphill)
                    VALUES
                     (%s, %s, %s, %s, %s, %s, %s)

                    ON CONFLICT (message_id, name)
                    DO UPDATE SET
                        is_deleted = FALSE,
                        cases = EXCLUDED.cases,
                        case_type = EXCLUDED.case_type,
                        channel = EXCLUDED.channel,
                        date = EXCLUDED.date,
                        is_uphill = EXCLUDED.is_uphill;
                """, (
                    message_date,
                    name,
                    channel,
                    case_type,
                    cases,
                    str(message_id),
                    is_uphill
                ))
        print(
            f"✅ Saved | {name} | {case_type} | +{cases} | "
            f"date={message_date} | msg={message_id}"
        )
    except Exception as e:
        print("❌ DB error:", e)
        
async def save_case_async(
    name: str,
    channel: str,
    case_type: str,
    cases: int,
    message_id: int,
    message_date,
    is_uphill: bool = False
):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        save_case_pg,
        name,
        channel,
        case_type,
        cases,
        message_id,
        message_date,
        is_uphill
    )

def is_message_saved(message_id: int) -> bool:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM cases WHERE message_id = %s LIMIT 1",
                    (str(message_id),)
                )
                return cur.fetchone() is not None
    except Exception as e:
        print("❌ DB check error:", e)
        return True  # กันพลาด ไม่ insert ซ้ำ
        
# ===== ASYNC WRAPPER (FIX 2) =====
async def is_message_saved_async(message_id: int) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        is_message_saved,   # ← เรียกของเดิม
        message_id
    )      

def get_last_online():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM bot_meta WHERE key = 'last_online'"
                )
                row = cur.fetchone()
                if not row:
                    return None

                dt = datetime.fromisoformat(row[0])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TH_TZ)

                return dt
    except Exception as e:
        print("❌ get_last_online error:", e)
        return None


def set_last_online(dt: datetime):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bot_meta (key, value)
                    VALUES ('last_online', %s)
                    ON CONFLICT (key)
                    DO UPDATE SET value = EXCLUDED.value
                """, (dt.isoformat(),))
    except Exception as e:
        print("❌ set_last_online error:", e)
 
def get_last_daily_report():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM bot_meta WHERE key = 'last_daily_report'"
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as e:
        print("❌ get_last_daily_report error:", e)
        return None


def set_last_daily_report(date_str: str):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bot_meta (key, value)
                    VALUES ('last_daily_report', %s)
                    ON CONFLICT (key)
                    DO UPDATE SET value = EXCLUDED.value
                """, (date_str,))
    except Exception as e:
        print("❌ set_last_daily_report error:", e)

def get_post_summary_by_range(start_date, end_date):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'normal') AS normal_posts,
                        COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'case10') AS point10_posts
                    FROM cases
                    WHERE date BETWEEN %s AND %s
                      AND is_deleted = FALSE
                """, (start_date, end_date))
                row = cur.fetchone()
                return row if row else (0, 0)
    except Exception as e:
        print("❌ get_post_summary_by_range DB error:", e)
        return (0, 0)


def get_post_summary_by_name_and_date(name, date):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'normal') AS normal_posts,
                        COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'case10') AS point10_posts
                    FROM cases
                    WHERE date = %s
                      AND name ILIKE %s
                      AND is_deleted = FALSE
                """, (date, f"%{name}%"))
                row = cur.fetchone()
                return row if row else (0, 0)
    except Exception as e:
        print("❌ get_post_summary_by_name_and_date DB error:", e)
        return (0, 0)


def count_posts_by_type(start_date, end_date=None):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if end_date:
                    cur.execute("""
                        SELECT
                            COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'normal') AS normal_posts,
                            COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'case10') AS point10_posts,
                            COUNT(DISTINCT message_id) AS total_posts
                        FROM cases
                        WHERE date BETWEEN %s AND %s
                          AND is_deleted = FALSE
                    """, (start_date, end_date))
                else:
                    cur.execute("""
                        SELECT
                            COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'normal') AS normal_posts,
                            COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'case10') AS point10_posts,
                            COUNT(DISTINCT message_id) AS total_posts
                        FROM cases
                        WHERE date = %s
                          AND is_deleted = FALSE
                    """, (start_date,))
                row = cur.fetchone()
                return row if row else (0, 0, 0)
    except Exception as e:
        print("❌ count_posts_by_type DB error:", e)
        return (0, 0, 0)

def write_audit(
    action: str,
    actor: str = None,
    target: str = None,
    channel: str = None,
    message_id: str = None,
    detail: str = None
):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO audit_logs
                        (action, actor, target, channel, message_id, detail)
                    VALUES
                        (%s, %s, %s, %s, %s, %s)
                """, (
                    action,
                    actor,
                    target,
                    channel,
                    message_id,
                    detail
                ))
    except Exception as e:
        print("❌ audit log error:", e)
# ===== ASYNC WRAPPER (FIX AUDIT) =====
async def write_audit_async(**kwargs):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: write_audit(**kwargs)
    )

def get_post_summary_by_date(date):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'normal') AS normal_posts,
                        COUNT(DISTINCT message_id) FILTER (WHERE case_type = 'case10') AS point10_posts
                    FROM cases
                    WHERE date = %s
                      AND is_deleted = FALSE
                """, (date,))
                row = cur.fetchone()
                return row if row else (0, 0)
    except Exception as e:
        print("❌ get_post_summary_by_date DB error:", e)
        return (0, 0)


def get_today_summary():
    today = today_th()

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        SUM(cases) FILTER (WHERE case_type = 'normal') AS normal_cases,
                        SUM(cases) FILTER (WHERE case_type = 'case10') AS point10_cases
                    FROM cases
                    WHERE date = %s
                      AND is_deleted = FALSE
                """, (today,))
                row = cur.fetchone()

                if not row:
                    return 0, 0, 0

                normal = row[0] or 0
                point10 = row[1] or 0
                total = normal + point10

                return normal, point10, total

    except Exception as e:
        print("❌ get_today_summary DB error:", e)
        # กัน dashboard พังทั้งระบบ
        return 0, 0, 0


async def random_react_dashboard(msg, count=5):
    try:
        # ลบ reaction เก่า (ถ้าอยากให้โล่ง)
        await msg.clear_reactions()

        emojis = random.sample(
            DASHBOARD_REACTIONS,
            k=min(count, len(DASHBOARD_REACTIONS))
        )

        for e in emojis:
            await msg.add_reaction(e)

    except Exception as e:
        print("⚠️ reaction error:", e)
def seconds_until_next_quarter():
    now = now_th()
    minute = now.minute
    second = now.second

    next_quarter = ((minute // 15) + 1) * 15
    if next_quarter == 60:
        next_time = now.replace(
            minute=0, second=0, microsecond=0
        ) + timedelta(hours=1)
    else:
        next_time = now.replace(
            minute=next_quarter, second=0, microsecond=0
        )

    return (next_time - now).total_seconds()

def parse_date_smart(date_str: str):
    parts = date_str.split("/")

    now = now_th()

    if len(parts) == 3:
        d, m, y = map(int, parts)
    elif len(parts) == 2:
        d, m = map(int, parts)
        y = now.year
    else:
        raise ValueError("invalid date format")

    target = datetime(y, m, d, tzinfo=TH_TZ).date()

    # ถ้าไม่มีปี และวันที่อยู่ในอนาคต → ถอยปี
    if len(parts) == 2 and target > now.date():
        target = datetime(y - 1, m, d, tzinfo=TH_TZ).date()

    return target

def get_last_body_sync():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT value FROM bot_meta
                    WHERE key = 'body_last_synced'
                """)
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as e:
        print("❌ get_last_body_sync error:", e)
        return None


def set_last_body_sync(date_str: str):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bot_meta (key, value)
                    VALUES ('body_last_synced', %s)
                    ON CONFLICT (key)
                    DO UPDATE SET value = EXCLUDED.value
                """, (date_str,))
    except Exception as e:
        print("❌ set_last_body_sync error:", e)

def get_body_dashboard_message_id():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT value FROM bot_meta
                    WHERE key = 'body_dashboard_message_id'
                """)
                row = cur.fetchone()
                return int(row[0]) if row else None
    except Exception as e:
        print("❌ get_body_dashboard_message_id error:", e)
        return None


def set_body_dashboard_message_id(msg_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_meta (key, value)
                VALUES ('body_dashboard_message_id', %s)
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value
            """, (str(msg_id),))

# ======================
# UTILS
# ======================
def is_uphill_case(message_content: str) -> bool:
    return "(ขึ้นเขา)" in message_content

def normalize_name(name: str):
    if not name:
        return ""

    name = name.lower()

    # ลบ +เลขหน้า
    name = re.sub(r"\+?\d+", "", name)

    # ลบ tag [xxx]
    name = re.sub(r"\[.*?\]", "", name)

    # เปลี่ยน whitespace ทุกชนิด → space เดียว
    name = re.sub(r"\s+", " ", name)

    return name.strip()



def get_week_range_sun_sat():
    today = today_th()
    start = today - timedelta(days=(today.weekday() + 1) % 7)
    end = start + timedelta(days=6)
    return start, end

def process_case_message(message):
    # เลือกประเภทเคส
    if message.channel.id == CASE10_CHANNEL_ID:
        case_type = "case10"
        case_value = 2
    elif message.channel.id in NORMAL_CHANNEL_IDS:
        case_type = "normal"
        case_value = 1
    else:
        return

    message_date = message.created_at.astimezone(TH_TZ).date()
    uphill = is_uphill_case(message.content)
    unique_members = set(message.mentions)

    for member in unique_members:
        asyncio.create_task(
            save_case_async(
                member.display_name,
                message.channel.name,
                case_type,
                case_value,
                message.id,
                message_date,
                uphill
            )
        )

def get_body_work_window(work_date):
    """
    วันทำงาน = 06:00 ของ work_date
            → 05:59 ของวันถัดไป
    """
    start = datetime.combine(
        work_date,
        datetime.min.time(),
        tzinfo=TH_TZ
    ).replace(hour=6, minute=0)

    end = start + timedelta(days=1)

    return start, end

def save_body_case_daily_split(result):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO body_case_daily (
                    work_date,
                    start_time,
                    end_time,
                    chub_posts,
                    wrap_posts,
                    total_posts,
                    synced_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (work_date)
                DO UPDATE SET
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    chub_posts = EXCLUDED.chub_posts,
                    wrap_posts = EXCLUDED.wrap_posts,
                    total_posts = EXCLUDED.total_posts,
                    synced_at = NOW();
            """, (
                result["date"],
                result["start"],
                result["end"],
                result["chub"],
                result["wrap"],
                result["total"]
            ))

def now_th():
    return datetime.now(TH_TZ)

def today_th():
    return now_th().date()
    
def build_case_footer(
    normal_cases,
    normal_posts,
    point10_cases,
    point10_posts
):
    total_cases = normal_cases + point10_cases
    total_posts = normal_posts + point10_posts

    return (
        f"📊 รวมทั้งหมด: {total_cases} เคส | {total_posts} คดี\n"
        f"📂 คดีปกติ: {normal_cases} เคส ({normal_posts} คดี)\n"
        f"🚨 คดีจุด 10: {point10_cases} เคส ({point10_posts} คดี)\n"
        f"🔒 ระบบป้องกันการนับซ้ำอัตโนมัติ"
    )
def build_today_embed():
    today = today_th()

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, case_type, COUNT(*) AS inc, SUM(cases) AS total
                    FROM cases
                    WHERE date = %s
                    AND is_deleted = FALSE
                    GROUP BY name, case_type
                """, (today,))
                rows = cur.fetchall()
    except Exception as e:
        print("❌ build_today_embed DB error:", e)
        rows = []

    if not rows:
        embed = Embed(
            description="📭 วันนี้ยังไม่มีคดี",
            color=0x2f3136
        )
        embed.set_footer(text=SYSTEM_FOOTER)
        return embed

    embed = Embed(
        title="📊 Case Summary — Today",
        description=f"📅 วันที่: {today.strftime('%d/%m/%Y')}",
        color=0x2ecc71
    )

    summary = {}
    total_normal_posts = 0
    total_point10_posts = 0

    for name, ctype, inc, total in rows:
        summary.setdefault(name, {
            "normal_cases": 0, "normal_posts": 0,
            "point10_cases": 0, "point10_posts": 0
        })

        if ctype == "normal":
            summary[name]["normal_cases"] += total
            summary[name]["normal_posts"] += inc
            total_normal_posts += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc
            total_point10_posts += inc

    for name in sorted(summary.keys(), key=normalize_name):
        d = summary[name]
        value = ""
        if d["normal_cases"]:
            value += f"📂 คดีปกติ: {d['normal_cases']} เคส ({d['normal_posts']} คดี)\n"
        if d["point10_cases"]:
            value += f"🚨 คดีจุด 10: {d['point10_cases']} เคส ({d['point10_posts']} คดี)\n"

        value += f"📊 **รวมทั้งหมด: {d['normal_cases'] + d['point10_cases']} เคส**"
        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    # 🔒 กัน DB ล่มตอน footer อีกชั้น
    try:
        normal_posts, point10_posts = get_post_summary_by_date(today)
    except Exception as e:
        print("❌ footer summary error:", e)
        normal_posts, point10_posts = 0, 0

    embed.set_footer(
        text=(
            build_case_footer(
                normal_cases=sum(v["normal_cases"] for v in summary.values()),
                normal_posts=normal_posts,
                point10_cases=sum(v["point10_cases"] for v in summary.values()),
                point10_posts=point10_posts
            )
            + "\n"
            + SYSTEM_FOOTER
        )
    )

    return embed

def get_top_officers_today(limit=5):
    today = today_th()
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, SUM(cases) AS total_cases
                    FROM cases
                    WHERE date = %s
                      AND is_deleted = FALSE
                    GROUP BY name
                    ORDER BY total_cases DESC
                    LIMIT %s
                """, (today, limit))
                return cur.fetchall()
    except Exception as e:
        print("❌ get_top_officers_today DB error:", e)
        return []

def build_top_officers_text(limit=5):
    rows = get_top_officers_today(limit)

    if not rows:
        return "ยังไม่มีข้อมูล"

    medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
    lines = []

    for i, (name, total) in enumerate(rows):
        medal = medals[i] if i < len(medals) else "👮"
        lines.append(f"{medal} {name} — {total} เคส")

    return "\n".join(lines)
 
 
def build_dashboard_embed():
    # 🔒 ชั้นที่ 1: summary หลัก (กัน DB ล่มแล้วในฟังก์ชัน)
    normal, point10, total = get_today_summary()

    # 🔒 ชั้นที่ 2: footer (กัน DB ล่มแยกอีกชั้น)
    try:
        normal_posts, point10_posts = get_post_summary_by_date(today_th())
    except Exception as e:
        print("❌ dashboard footer DB error:", e)
        normal_posts, point10_posts = 0, 0

    embed = Embed(
        title="📊 Police Case Management Dashboard",
        description=(
            f"📅 วันที่: {today_th().strftime('%d/%m/%Y')}\n"
            f"⏱️ อัพเดทล่าสุด: {now_th().strftime('%H:%M')}"
        ),
        color=0x3498db
    )

    embed.add_field(
        name="📈 Summary Today",
        value=(
            f"📂 คดีปกติ: {normal} เคส ({normal_posts} คดี)\n"
            f"🚨 คดีจุด 10: {point10} เคส ({point10_posts} คดี)\n"
            f"📊 รวมทั้งหมด: **{total} เคส**"
        ),
        inline=False
    )

    embed.add_field(
        name="👮 Top Officers (Today)",
        value=build_top_officers_text(),
        inline=False
    )

    embed.set_footer(
        text=f"🔄 อัพเดททุก 15 นาที\n{SYSTEM_FOOTER}"
    )

    return embed

def get_dashboard_message_id():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT value FROM bot_meta
                    WHERE key = 'dashboard_message_id'
                """)
                row = cur.fetchone()
                return int(row[0]) if row else None
    except Exception as e:
        print("❌ get_dashboard_message_id error:", e)
        return None

def set_dashboard_message_id(msg_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_meta (key, value)
                VALUES ('dashboard_message_id', %s)
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value
            """, (str(msg_id),))

async def dashboard_updater():
    await bot.wait_until_ready()
    channel = bot.get_channel(DASHBOARD_CHANNEL_ID)

    while not bot.is_closed():
        wait_sec = seconds_until_next_quarter()
        print(f"⏳ Dashboard sync in {int(wait_sec)}s")
        await asyncio.sleep(wait_sec)

        try:
            embed = build_dashboard_embed()
        except Exception as e:
            print("❌ build_dashboard_embed crash:", e)
            continue  # 🔥 กัน loop ตาย

        try:
            msg_id = get_dashboard_message_id()
        except Exception as e:
            print("❌ get_dashboard_message_id DB error:", e)
            continue

        try:
            if msg_id:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                await random_react_dashboard(msg, count=5)
            else:
                msg = await channel.send(embed=embed)
                await msg.pin()
                await random_react_dashboard(msg, count=5)
                set_dashboard_message_id(msg.id)

        except Exception as e:
            print("❌ Dashboard update error:", e)

def get_top_officers_week(limit=5):
    start, end = get_week_range_sun_sat()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    name,
                    SUM(cases) AS total_cases,
                    COUNT(DISTINCT message_id) AS total_posts
                FROM cases
                WHERE date BETWEEN %s AND %s
                  AND is_deleted = FALSE
                GROUP BY name
                ORDER BY total_cases DESC
                LIMIT %s
            """, (start, end, limit))
            return cur.fetchall(), start, end

def build_weekly_ranking_embed():
    rows, start, end = get_top_officers_week()

    embed = Embed(
        title="🥇 Officer Ranking — This Week",
        description=(
            f"📆 {start.strftime('%d/%m')} → {end.strftime('%d/%m')}\n"
            "⏱️ Updated every Saturday at 23:59"
        ),
        color=0xf1c40f
    )

    if not rows:
        embed.description += "\n\n📭 ยังไม่มีข้อมูลในสัปดาห์นี้"
        embed.set_footer(text=SYSTEM_FOOTER)
        return embed

    medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
    lines = []

    for i, (name, cases, posts) in enumerate(rows):
        medal = medals[i] if i < len(medals) else "👮"
        lines.append(
            f"{medal} {name} — **{cases} เคส** ({posts} คดี)"
        )

    embed.add_field(
        name="🏆 Top Officers",
        value="\n".join(lines),
        inline=False
    )

    embed.set_footer(
        text=(
            "📊 Weekly ranking (Sun–Sat)\n"
            "⏰ Updated every Saturday at 23:59\n"
            "Created by Lion Kuryru"
        )
    )
    return embed


def get_weekly_ranking_message_id():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT value FROM bot_meta
                    WHERE key = 'weekly_ranking_message_id'
                """)
                row = cur.fetchone()
                return int(row[0]) if row else None
    except Exception as e:
        print("❌ get_weekly_ranking_message_id error:", e)
        return None

def set_weekly_ranking_message_id(msg_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_meta (key, value)
                VALUES ('weekly_ranking_message_id', %s)
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value
            """, (str(msg_id),))

def seconds_until_saturday_2359():
    now = now_th()

    # weekday(): Mon=0 ... Sun=6 → Saturday = 5
    days_until_sat = (5 - now.weekday()) % 7

    target = (now + timedelta(days=days_until_sat)).replace(
        hour=23, minute=59, second=0, microsecond=0
    )

    # ถ้าเลยเวลาเสาร์ 23:59 ของสัปดาห์นี้แล้ว → ขยับไปสัปดาห์หน้า
    if target <= now:
        target += timedelta(days=7)

    return (target - now).total_seconds()
    
async def weekly_ranking_updater():
    await bot.wait_until_ready()
    channel = bot.get_channel(DASHBOARD_CHANNEL_ID)

    while not bot.is_closed():
        wait_sec = seconds_until_saturday_2359()
        print(f"⏳ Weekly ranking update in {int(wait_sec)}s")
        await asyncio.sleep(wait_sec)

        try:
            embed = build_weekly_ranking_embed()
        except Exception as e:
            print("❌ weekly embed error:", e)
            await asyncio.sleep(60)
            continue

        try:
            msg_id = get_weekly_ranking_message_id()
        except Exception as e:
            print("❌ weekly msg_id DB error:", e)
            await asyncio.sleep(60)
            continue

        try:
            if msg_id:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                await random_react_dashboard(msg, count=10)
            else:
                msg = await channel.send(embed=embed)
                await msg.pin()
                await random_react_dashboard(msg, count=10)
                set_weekly_ranking_message_id(msg.id)
        except Exception as e:
            print("❌ Weekly ranking update error:", e)

        await asyncio.sleep(60)


def build_body_dashboard_embed(result, work_date):
    embed = Embed(
        title="🧾 Body Case Dashboard",
        description=(
            f"📅 วันที่ปฏิบัติงาน: {work_date}\n"
            f"⏰ ช่วงเวลา: {result['start'].strftime('%H:%M')} → {result['end'].strftime('%H:%M')}\n\n"
            f"🧪 ชุบ: {result['wrap']} เคส\n"
            f"🧳 ช่วยอุ้ม/ห่อ: {result['chub']} เคส\n"
            f"📦 **รวมทั้งหมด: {result['total']} เคส**\n\n"
            f"🧾 เขียนลง Google Sheet เรียบร้อยแล้ว"
        ),
        color=0xe67e22
    )

    embed.set_footer(
        text=f"🔄 อัปเดทล่าสุด {now_th().strftime('%d/%m/%Y %H:%M')} • Auto-sync 06:05"
    )
    return embed


# ======================
# DISCORD SETUP
# ======================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.check
async def restrict_commands_to_channel(ctx):
    # ไม่ให้ใช้ใน DM
    if ctx.guild is None:
        return False

    return ctx.channel.id in ALLOWED_COMMAND_CHANNELS

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        try:
            await ctx.author.send(
                "❌ ใช้คำสั่งบอทได้เฉพาะห้องที่กำหนดเท่านั้น"
            )
        except:
            pass

# ======================
# EVENTS
# ======================

async def daily_today_report():
    await bot.wait_until_ready()

    while not bot.is_closed():
        now = now_th()

        target = now.replace(
            hour=23, minute=59, second=0, microsecond=0
        )

        if now >= target:
            target += timedelta(days=1)

        sleep_seconds = (target - now).total_seconds()
        await asyncio.sleep(sleep_seconds)

        today_str = today_th().isoformat()
        last_sent = get_last_daily_report()

        if last_sent == today_str:
            print("ℹ️ Daily report already sent today, skip")
        else:
            channel = bot.get_channel(DAILY_REPORT_CHANNEL_ID)
            if channel:
                embed = build_today_embed()
                await channel.send(embed=embed)
                set_last_daily_report(today_str)
                print("✅ Daily report sent")
                
        await asyncio.sleep(60)

async def daily_sheet_auto_sync():
    await bot.wait_until_ready()

    channel = bot.get_channel(DAILY_REPORT_CHANNEL_ID)

    while not bot.is_closed():
        now = now_th()

        target = now.replace(
            hour=23, minute=59, second=0, microsecond=0
        )

        if now >= target:
            target += timedelta(days=1)

        sleep_seconds = (target - now).total_seconds()
        print(f"⏳ Auto sheet sync in {int(sleep_seconds)}s")
        await asyncio.sleep(sleep_seconds)

        target_date = today_th()

        try:
            written, skipped = await asyncio.to_thread(
                run_daily_case_sync,
                target_date
            )

            print(
                f"✅ Auto Sheet Sync {target_date} | "
                f"written={written} skipped={len(skipped)}"
            )

            # 🔔 แจ้งผลใน Discord
            if channel:
                embed = Embed(
                    title="📊 Auto Sheet Sync Completed",
                    description=f"📅 วันที่: {target_date.strftime('%d/%m/%Y')}",
                    color=0x2ecc71
                )
                embed.add_field(
                    name="✅ เขียนสำเร็จ",
                    value=f"{written} คน",
                    inline=False
                )

                if skipped:
                    embed.add_field(
                        name="⚠️ ไม่พบชื่อในชีท",
                        value="\n".join(skipped),
                        inline=False
                    )

                embed.set_footer(text="⏰ Auto Sync เวลา 23:59")
                await channel.send(embed=embed)

        except Exception as e:
            print("❌ Auto Sheet Sync error:", e)
            if channel:
                await channel.send(f"❌ Auto Sheet Sync Error: `{e}`")

        await asyncio.sleep(60)

async def body_case_auto_sync():
    await bot.wait_until_ready()
    channel = bot.get_channel(BODY_DASHBOARD_CHANNEL_ID)

    while not bot.is_closed():
        now = now_th()

        target = now.replace(hour=6, minute=5, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)

        await asyncio.sleep((target - now).total_seconds())

        # 🔑 ใช้ "เมื่อวาน" เป็นวันทำงาน
        work_date = today_th() - timedelta(days=1)

        # 🔒 LOCK กันยิงซ้ำ
        last_synced = get_last_body_sync()
        if last_synced == work_date.isoformat():
            print("ℹ️ Body case already synced, skip")
            await asyncio.sleep(60)
            continue

        # 🔢 นับเคส
        result = await count_body_cases_split(work_date)

        # 💾 บันทึก DB
        save_body_case_daily_split(result)

        # 📊 เขียน Google Sheet (Body Case)
        write_body_case_total(
            work_date,
            result["total"]
        )

        # 🔒 set lock
        set_last_body_sync(work_date.isoformat())

        # ======================
        # 🧾 BUILD DASHBOARD EMBED
        # ======================
        embed = build_body_dashboard_embed(result, work_date)

        embed.set_footer(
            text=f"🔄 อัปเดทล่าสุด {now_th().strftime('%d/%m/%Y %H:%M')} • Auto-sync 06:05"
        )

        # ======================
        # 📌 DASHBOARD MESSAGE (send ครั้งแรก / edit ครั้งถัดไป)
        # ======================
        msg_id = get_body_dashboard_message_id()

        try:
            if msg_id:
                # 🔁 แก้ข้อความเดิม
                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                print("🔄 Body dashboard updated")
            else:
                # 🆕 ครั้งแรก
                msg = await channel.send(embed=embed)
                await msg.pin()
                set_body_dashboard_message_id(msg.id)
                print("🆕 Body dashboard created")

        except Exception as e:
            print("❌ Body dashboard error:", e)

        await asyncio.sleep(60)
        
@bot.event
async def on_ready():
    print(f"🤖 Bot online: {bot.user}")

    # รอให้ bot stable
    await asyncio.sleep(5)

    # ✅ เชคโพสช่วง offline
    asyncio.create_task(recovery_backfill())

    # daily report เหมือนเดิม
    asyncio.create_task(daily_today_report())
    asyncio.create_task(dashboard_updater()) 
    
    asyncio.create_task(weekly_ranking_updater())
    # ✅ AUTO SYNC GOOGLE SHEET
    asyncio.create_task(daily_sheet_auto_sync())
    asyncio.create_task(body_case_auto_sync())

    # ✅ ตรวจสอบสุขภาพ DB
    asyncio.create_task(db_health_check())

async def db_health_check():
    await bot.wait_until_ready()

    print("🩺 DB Health Check started")

    fail_count = 0
    last_email_time = 0
    CHECK_INTERVAL = 3600      # เช็คทุก 1 ชั่วโมง
    ALERT_INTERVAL = 3600      # ส่งเมลซ้ำได้ทุก 1 ชม. (กัน spam)

    while not bot.is_closed():
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")

            if fail_count > 0:
                print("🟢 DB RECOVERED")

            print("🟢 DB Health: OK")
            fail_count = 0
            last_email_time = 0  # รีเซ็ต cooldown เมล

        except Exception as e:
            fail_count += 1
            print(f"🚨 DB Health Check FAILED ({fail_count}):", e)

            now_ts = time.time()

            # ล่ม 2 รอบติด (≈ 2 ชม.) ค่อยแจ้งเมล
            if fail_count >= 2:
                if last_email_time == 0 or (now_ts - last_email_time) >= ALERT_INTERVAL:
                    send_email_alert(
                        subject="🚨 Railway DB DOWN - Police Bot",
                        body=(
                            "Database connection failed.\n\n"
                            "Railway PostgreSQL may be frozen or unreachable.\n"
                            "Action: Restart DB plugin in Railway.\n\n"
                            f"Fail count: {fail_count}\n"
                            f"Time: {now_th().strftime('%d/%m/%Y %H:%M:%S')}\n"
                            "Bot Status: ONLINE\n"
                            "DB Status: UNREACHABLE"
                        )
                    )
                    last_email_time = now_ts
                    print("📧 Resend alert sent (anti-spam)")

        await asyncio.sleep(CHECK_INTERVAL)

def get_last_checked_time():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT value FROM bot_meta
                    WHERE key = 'last_checked_message_time'
                """)
                row = cur.fetchone()
                if not row:
                    return None

                dt = datetime.fromisoformat(row[0])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TH_TZ)

                return dt
    except Exception as e:
        print("❌ get_last_checked_time error:", e)
        return None


def set_last_checked_time(dt: datetime):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bot_meta (key, value)
                    VALUES ('last_checked_message_time', %s)
                    ON CONFLICT (key)
                    DO UPDATE SET value = EXCLUDED.value
                """, (dt.isoformat(),))
    except Exception as e:
        print("❌ set_last_checked_time error:", e)


async def backfill_recent_cases(limit_per_channel=50):
    print("🔄 Backfill started")

    last_online = get_last_online()
    now = now_th()

    checked = 0
    found = 0
    recovered = 0

    for channel_id in [CASE10_CHANNEL_ID, *NORMAL_CHANNEL_IDS]:
        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        async for msg in channel.history(limit=limit_per_channel):
            checked += 1

            if msg.author.bot or not msg.mentions:
                continue

            # 👉 ถ้ามี last_online ใช้แบบเวลา
            if last_online and msg.created_at.astimezone(TH_TZ) <= last_online:
                continue

            found += 1

            if await is_message_saved_async(msg.id):
                continue

            process_case_message(msg)
            recovered += 1

            print(
                f"🧩 Backfilled | "
                f"msg={msg.id} | "
                f"channel={channel.name}"
            )

    # ✅ update เวลา หลัง backfill เสร็จ
    set_last_online(now_th())

    print("✅ Backfill finished")
    await write_audit_async(
        action="BACKFILL",
        detail=(
            f"checked={checked} "
            f"found={found} "
            f"recovered={recovered}"
        )
    )

async def recovery_backfill(limit_per_channel=200):
    print("🔄 Recovery backfill started")

    last_time = get_last_checked_time()
    now = now_th()

    # ถ้าไม่เคยเชคมาก่อน → ย้อนหลัง 1 วัน (กันพลาด deploy แรก)
    if not last_time:
        last_time = now - timedelta(days=1)
        print("ℹ️ No last_checked_time, fallback 1 day")

    for channel_id in [CASE10_CHANNEL_ID, *NORMAL_CHANNEL_IDS]:
        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        async for msg in channel.history(
            limit=limit_per_channel,
            after=last_time
        ):
            if msg.author.bot or not msg.mentions:
                continue

            # กันซ้ำด้วย DB (ของคุณมีอยู่แล้ว)
            if await is_message_saved_async(msg.id):
                continue

            process_case_message(msg)

            print(
                f"🧩 Recovered | "
                f"msg={msg.id} | "
                f"channel={channel.name}"
            )

    # อัปเดต checkpoint หลังเชคเสร็จ
    set_last_checked_time(now)
    print("✅ Recovery backfill finished")

@bot.event
async def on_message(message):
    # 1️⃣ ให้บอทประมวลผลคำสั่งก่อน
    await bot.process_commands(message)

    # 2️⃣ ข้าม bot
    if message.author.bot:
        return

    # 3️⃣ ถ้าเป็นคำสั่ง (ขึ้นต้นด้วย !) ไม่เอาไปนับเคส
    if message.content.startswith("!"):
        return

    # 4️⃣ ไม่มี mention ก็ไม่ใช่เคส
    if not message.mentions:
        return

    # 5️⃣ เลือกประเภทเคส
    if message.channel.id == CASE10_CHANNEL_ID:
        case_type = "case10"
        case_value = 2
    elif message.channel.id in NORMAL_CHANNEL_IDS:
        case_type = "normal"
        case_value = 1
    else:
        return

    message_date = message.created_at.astimezone(TH_TZ).date()
    uphill = is_uphill_case(message.content)

    mentions = message.mentions
    unique_members = set(mentions)

    if len(mentions) != len(unique_members):
        print(
            f"⚠️ Duplicate mention detected | "
            f"msg={message.id} | "
            f"{len(mentions)} → {len(unique_members)}"
        )

    for member in unique_members:
        asyncio.create_task(
            save_case_async(
                member.display_name,
                message.channel.name,
                case_type,
                case_value,
                message.id,
                message_date,
                uphill
            )
        )


@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return

    # 🔒 สนใจเฉพาะห้องคดี
    if message.channel.id not in [CASE10_CHANNEL_ID, *NORMAL_CHANNEL_IDS]:
        return

    delete_type = "🧑‍✈️ self-delete"
    deleted_by = message.author.display_name

    # 🔍 พยายามดู audit log (ถ้ามี)
    try:
        async for entry in message.guild.audit_logs(
            limit=5,
            action=discord.AuditLogAction.message_delete
        ):
            if entry.target.id == message.author.id:
                delete_type = "🛡️ mod-delete"
                deleted_by = entry.user.display_name
                break
    except Exception:
        delete_type = "❓ unknown"
        deleted_by = "unknown"

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE cases
                    SET is_deleted = TRUE
                    WHERE message_id = %s
                      AND is_deleted = FALSE
                    """,
                    (str(message.id),)
                )
                deleted = cur.rowcount

        # log เฉพาะตอนลบเคสจริง
        if deleted > 0:
            print(
                f"{delete_type} | "
                f"msg={message.id} | "
                f"channel={message.channel.name} | "
                f"author={message.author.display_name} | "
                f"deleted_by={deleted_by} | "
                f"rows={deleted}"
            )

        write_audit(
            action="DELETE_CASE",
            actor=deleted_by,
            target=message.author.display_name,
            channel=message.channel.name,
            message_id=str(message.id),
            detail=delete_type
        )

    except Exception as e:
        print("❌ DB delete error:", e)


@bot.event
async def on_message_edit(before, after):
    # สนใจเฉพาะห้องคดี
    if after.channel.id not in [CASE10_CHANNEL_ID, *NORMAL_CHANNEL_IDS]:
        return

    if after.author.bot:
        return

    print(f"✏️ Message edited | msg={after.id}")

    # 1️⃣ soft-delete เคสเดิมทั้งหมดของ message นี้
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE cases
                    SET is_deleted = TRUE
                    WHERE message_id = %s
                      AND is_deleted = FALSE
                    """,
                    (str(after.id),)
                )
                deleted = cur.rowcount
        print(f"🗑️ Soft-deleted {deleted} old cases | msg={after.id}")
    except Exception as e:
        print("❌ DB delete error (edit):", e)
        return

    # 2️⃣ ถ้าแก้แล้วไม่มี mention → ถือว่าตั้งใจลบเคส
    if not after.mentions:
        print(f"ℹ️ Edit removed mentions | msg={after.id}")
        return

    # 3️⃣ นับใหม่จากข้อความล่าสุด
    if after.channel.id == CASE10_CHANNEL_ID:
        case_type = "case10"
        case_value = 2
    elif after.channel.id in NORMAL_CHANNEL_IDS:
        case_type = "normal"
        case_value = 1
    else:
        return

    message_date = after.created_at.astimezone(TH_TZ).date()
    uphill = is_uphill_case(after.content)
    unique_members = set(after.mentions)

    for member in unique_members:
        asyncio.create_task(
            save_case_async(
                member.display_name,
                after.channel.name,
                case_type,
                case_value,
                after.id,
                message_date,
                uphill
            )
        )


    print(f"✅ Recounted cases | msg={after.id}")

    write_audit(
        action="EDIT_CASE",
        actor=after.author.display_name,
        channel=after.channel.name,
        message_id=str(after.id),
        detail=f"mentions={len(unique_members)}"
    )

# ======================
# COMMANDS
# ======================

@bot.command()
async def today(ctx):
    embed = build_today_embed()
    await ctx.send(embed=embed)

@bot.command()
async def me(ctx):
    today = today_th()
    name = ctx.author.display_name

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT case_type, COUNT(*) AS inc, SUM(cases) AS total
                FROM cases
                WHERE date = %s
                    AND name = %s
                    AND is_deleted = FALSE
                GROUP BY case_type
            """, (today, name))
            rows = cur.fetchall()

    if not rows:
        embed = Embed(
            description="📭 วันนี้คุณยังไม่มีคดี",
            color=0x2f3136
        )
        embed.set_footer(text=SYSTEM_FOOTER)
        await ctx.send(embed=embed)
        return

    embed = Embed(
        title="📊 Case Summary — Me",
        description=f"📅 วันที่: {today.strftime('%d/%m/%Y')}\n👤 เจ้าหน้าที่: {name}",
        color=0x2ecc71
    )

    total_posts_all = 0
    total_normal_posts = 0
    total_point10_posts = 0

    for ctype, inc, total in rows:
        label = "📂 คดีปกติ" if ctype == "normal" else "🚨 คดีจุด 10"
        embed.add_field(
            name=label,
            value=f"{total} เคส ({inc} คดี)",
            inline=False
        )

        total_posts_all += inc
        if ctype == "normal":
            total_normal_posts += inc
        else:
            total_point10_posts += inc

    embed.set_footer(
        text=build_case_footer(
            normal_cases=sum(total for ctype, inc, total in rows if ctype == "normal"),
            normal_posts=total_normal_posts,
            point10_cases=sum(total for ctype, inc, total in rows if ctype != "normal"),
            point10_posts=total_point10_posts
        ) + "\n" + SYSTEM_FOOTER
    )

    await ctx.send(embed=embed)

@bot.command()
async def date(ctx, date_str: str):
    try:
        target = parse_date_smart(date_str)
    except:
        await ctx.send("❌ ใช้ `!date DD/MM` หรือ `!date DD/MM/YYYY`")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*) AS inc, SUM(cases) AS total
                FROM cases
                WHERE date = %s
                AND is_deleted = FALSE
                GROUP BY name, case_type
            """, (target,))
            rows = cur.fetchall()

    if not rows:
        await ctx.send(embed=Embed(
            description=f"📭 วันที่ {date_str} ไม่มีคดี",
            color=0x2f3136
        ))
        return

    embed = Embed(
        title="📊 Case Summary — Date",
        description=f"📅 วันที่: {date_str}",
        color=0x2ecc71
    )

    summary = {}
    total_posts_all = 0
    total_normal_posts = 0
    total_point10_posts = 0

    for name, ctype, inc, total in rows:
        summary.setdefault(name, {
            "normal_cases": 0, "normal_posts": 0,
            "point10_cases": 0, "point10_posts": 0
        })

        if ctype == "normal":
            summary[name]["normal_cases"] += total
            summary[name]["normal_posts"] += inc
            total_normal_posts += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc
            total_point10_posts += inc

        total_posts_all += inc

    for name in sorted(summary.keys(), key=normalize_name):
        data = summary[name]
        value = ""
        if data["normal_cases"]:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"]:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)\n"

        value += f"📊 **รวมทั้งหมด: {data['normal_cases'] + data['point10_cases']} เคส**"
        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    embed.set_footer(
        text=build_case_footer(
            normal_cases=sum(v["normal_cases"] for v in summary.values()),
            normal_posts=total_normal_posts,
            point10_cases=sum(v["point10_cases"] for v in summary.values()),
            point10_posts=total_point10_posts
        ) + "\n" + SYSTEM_FOOTER
    )

    await ctx.send(embed=embed)

@bot.command()
async def week(ctx):
    start, end = get_week_range_sun_sat()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*) AS inc, SUM(cases) AS total
                FROM cases
                WHERE date BETWEEN %s AND %s
                    AND is_deleted = FALSE
                GROUP BY name, case_type
            """, (start, end))
            rows = cur.fetchall()

    if not rows:
        await ctx.send(embed=Embed(
            description="📭 ไม่มีข้อมูลในสัปดาห์นี้",
            color=0x2f3136
        ))
        return

    embed = Embed(
        title="📊 Case Summary — Week",
        description=f"📆 ช่วงเวลา: {start.strftime('%d/%m')} → {end.strftime('%d/%m')}",
        color=0x2ecc71
    )

    summary = {}
    total_normal_posts = 0
    total_point10_posts = 0
    total_posts_all = 0


    for name, ctype, inc, total in rows:
        summary.setdefault(name, {
            "normal_cases": 0, "normal_posts": 0,
            "point10_cases": 0, "point10_posts": 0
        })

        if ctype == "normal":
            summary[name]["normal_cases"] += total
            summary[name]["normal_posts"] += inc
            total_normal_posts += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc
            total_point10_posts += inc

        total_posts_all += inc

    for name in sorted(summary.keys(), key=normalize_name):
        data = summary[name]
        value = ""
        if data["normal_cases"]:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"]:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)\n"

        value += f"📊 **รวมทั้งหมด: {data['normal_cases'] + data['point10_cases']} เคส**"
        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    normal_posts, point10_posts = get_post_summary_by_range(start, end)

    embed.set_footer(
        text=build_case_footer(
            normal_cases=sum(v["normal_cases"] for v in summary.values()),
            normal_posts=normal_posts,
            point10_cases=sum(v["point10_cases"] for v in summary.values()),
            point10_posts=point10_posts
        ) + "\n" + SYSTEM_FOOTER
    )
    await ctx.send(embed=embed)

@bot.command()
async def check(ctx, *, keyword: str = None):
    if not keyword:
        await ctx.send("❌ ใช้ `!check ชื่อ`")
        return

    today = today_th()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*) AS inc, SUM(cases) AS total
                FROM cases
                WHERE date = %s
                    AND name ILIKE %s
                    AND is_deleted = FALSE
                GROUP BY name, case_type
            """, (today, f"%{keyword}%"))
            rows = cur.fetchall()

    if not rows:
        await ctx.send("ไม่พบข้อมูล")
        return

    embed = Embed(
        title="🔍 ผลการค้นหา (วันนี้)",
        description=f"ค้นหา: {keyword}",
        color=0x3498db
    )

    total_posts_all = 0
    total_normal_posts = 0
    total_point10_posts = 0
    summary = {}

    for name, ctype, inc, total in rows:
        summary.setdefault(name, {
            "normal_cases": 0, "normal_posts": 0,
            "point10_cases": 0, "point10_posts": 0
        })

        if ctype == "normal":
            summary[name]["normal_cases"] += total
            summary[name]["normal_posts"] += inc         
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc

        total_posts_all += inc

    for name in sorted(summary.keys(), key=normalize_name):
        data = summary[name]
        value = ""
        if data["normal_cases"]:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"]:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)"

        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    normal_posts, point10_posts = get_post_summary_by_name_and_date(
        keyword, today
    )

    embed.set_footer(
        text=build_case_footer(
            normal_cases=sum(v["normal_cases"] for v in summary.values()),
            normal_posts=normal_posts,
            point10_cases=sum(v["point10_cases"] for v in summary.values()),
        point10_posts=point10_posts
        ) + "\n" + SYSTEM_FOOTER
    )
    await ctx.send(embed=embed)

@bot.command()
async def checkdate(ctx, date_str: str, *, keyword: str):
    try:
        target = parse_date_smart(date_str)
    except:
        await ctx.send("❌ ใช้ `!checkdate DD/MM ชื่อ` หรือ `!checkdate DD/MM/YYYY ชื่อ`")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*) AS inc, SUM(cases) AS total
                FROM cases
                WHERE date = %s
                    AND name ILIKE %s
                    AND is_deleted = FALSE
                GROUP BY name, case_type
            """, (target, f"%{keyword}%"))
            rows = cur.fetchall()

    if not rows:
        await ctx.send("ไม่พบข้อมูล")
        return

    embed = Embed(
        title="🔍 ผลการค้นหา",
        description=f"📅 วันที่: {date_str}\nค้นหา: {keyword}",
        color=0x3498db
    )

    total_posts_all = 0
    summary = {}

    for name, ctype, inc, total in rows:
        summary.setdefault(name, {
            "normal_cases": 0, "normal_posts": 0,
            "point10_cases": 0, "point10_posts": 0
        })

        if ctype == "normal":
            summary[name]["normal_cases"] += total
            summary[name]["normal_posts"] += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc

        total_posts_all += inc

    for name in sorted(summary.keys(), key=normalize_name):
        data = summary[name]
        value = ""
        if data["normal_cases"]:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"]:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)"

        embed.add_field(name=f"👤 {name}", value=value, inline=False)
        
    normal_posts, point10_posts = get_post_summary_by_name_and_date(
        keyword, target
    )

    embed.set_footer(
        text=build_case_footer(
            normal_cases=sum(v["normal_cases"] for v in summary.values()),
            normal_posts=normal_posts,
            point10_cases=sum(v["point10_cases"] for v in summary.values()),
            point10_posts=point10_posts
        ) + "\n" + SYSTEM_FOOTER
    )
    await ctx.send(embed=embed)

@bot.command()
async def time(ctx):
    now = now_th()  # ✅ เรียกฟังก์ชันก่อน

    embed = Embed(
        title="⏰ Bot Time Check",
        color=0x3498db
    )
    embed.add_field(
        name="🕒 เวลาเซิร์ฟเวอร์บอท (TH)",
        value=now.strftime("%d/%m/%Y %H:%M:%S"),  # ✅ now เป็น datetime แล้ว
        inline=False
    )
    embed.add_field(
        name="🌏 Timezone",
        value="UTC+7 (Asia/Bangkok)",
        inline=False
    )
    embed.set_footer(text=SYSTEM_FOOTER)
    await ctx.send(embed=embed)


@bot.command()
async def posts(ctx):
    today = today_th()
    week_start, week_end = get_week_range_sun_sat()

    # วันนี้
    t_normal, t_point10, t_total = count_posts_by_type(today)

    # สัปดาห์นี้
    w_normal, w_point10, w_total = count_posts_by_type(week_start, week_end)

    embed = Embed(
        title="📊 สรุปคดี (นับจากโพส)",
        color=0x2ecc71
    )

    embed.add_field(
        name="📅 วันนี้",
        value=(
            f"📊 รวมทั้งหมด: **{t_total} คดี**\n"
            f"📂 คดีปกติ: {t_normal} คดี\n"
            f"🚨 คดีจุด 10: {t_point10} คดี"
        ),
        inline=False
    )

    embed.add_field(
        name="📆 สัปดาห์นี้ (อาทิตย์–เสาร์)",
        value=(
            f"📊 รวมทั้งหมด: **{w_total} คดี**\n"
            f"📂 คดีปกติ: {w_normal} คดี\n"
            f"🚨 คดีจุด 10: {w_point10} คดี\n"
            f"🗓️ {week_start.strftime('%d/%m')} → {week_end.strftime('%d/%m')}"
        ),
        inline=False
    )

    embed.set_footer(
        text=(
            "🔒 นับจากโพสจริง (message_id) | แท็กซ้ำไม่นับ\n"
            + SYSTEM_FOOTER
        )
    )

    await ctx.send(embed=embed)

@bot.command()
async def rankweek(ctx):
    embed = build_weekly_ranking_embed()
    await ctx.send(embed=embed)
    
@bot.command()
async def checkuphill(ctx, *, args: str = None):
    target_date = today_th()
    search_name = None

    if args:
        parts = args.split()

        # กรณีมีมากกว่า 1 token → ลองแยกวัน + ชื่อ
        if len(parts) >= 2:
            try:
                target_date = parse_date_smart(parts[0])
                search_name = " ".join(parts[1:])
            except:
                search_name = args
        else:
            # มี token เดียว → ลองเป็นวันที่ก่อน ถ้าไม่ได้ถือเป็นชื่อ
            try:
                target_date = parse_date_smart(parts[0])
            except:
                search_name = parts[0]

    with get_conn() as conn:
        with conn.cursor() as cur:
            if search_name:
                cur.execute("""
                    SELECT
                        name,
                        COUNT(DISTINCT message_id) AS posts,
                        SUM(cases) AS total_cases
                    FROM cases
                    WHERE date = %s
                      AND is_uphill = TRUE
                      AND is_deleted = FALSE
                      AND name ILIKE %s
                    GROUP BY name
                """, (target_date, f"%{search_name}%"))
            else:
                cur.execute("""
                    SELECT
                        name,
                        COUNT(DISTINCT message_id) AS posts,
                        SUM(cases) AS total_cases
                    FROM cases
                    WHERE date = %s
                      AND is_uphill = TRUE
                      AND is_deleted = FALSE
                    GROUP BY name
                """, (target_date,))

            rows = cur.fetchall()

    if not rows:
        await ctx.send(
            embed=Embed(
                description=f"📭 ไม่พบเคสขึ้นเขา วันที่ {target_date.strftime('%d/%m/%Y')}",
                color=0x2f3136
            )
        )
        return

    embed = Embed(
        title="🏔️ Uphill Case Summary",
        description=(
            f"📅 วันที่: {target_date.strftime('%d/%m/%Y')}\n"
            + (f"👤 ค้นหา: {search_name}" if search_name else "👥 ทุกเจ้าหน้าที่")
        ),
        color=0xe67e22
    )

    # ✅ เรียง A–Z ตามชื่อ (ไม่สนเลขหน้า)
    for name, posts, total in sorted(
        rows,
        key=lambda x: normalize_name(x[0])
    ):
        embed.add_field(
            name=f"👤 {name}",
            value=f"🏔️ {total} เคส ({posts} คดี)",
            inline=False
        )

    embed.set_footer(text=SYSTEM_FOOTER)
    await ctx.send(embed=embed)

from gspread.utils import rowcol_to_a1

def run_daily_case_sync(target_date):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(r"""
                SELECT
                    TRIM(
                        LOWER(
                            REGEXP_REPLACE(
                                REGEXP_REPLACE(name, '^\+?\d+\s*', ''),
                                '\[.*?\]\s*', '',
                                'g'
                            )
                        )
                    ) AS norm_name,
                    SUM(cases)
                    + COUNT(*) FILTER (WHERE is_uphill = TRUE)
                    AS total_cases
                FROM cases
                WHERE date = %s
                  AND is_deleted = FALSE
                GROUP BY norm_name
            """, (target_date,))
            rows = cur.fetchall()

    if not rows:
        return 0, []

    # 🔥 แก้ตรงนี้บรรทัดเดียว (สำคัญมาก)
    sheet = get_sheet_by_date(target_date)

    try:
        col = find_day_column_safe(target_date)
    except ValueError:
        print(
            f"⚠️ Skip sync: {target_date:%d/%m/%Y} "
            f"(ยังไม่มี column ใน worksheet)"
        )
        return 0, []

    case_col = col + 1

    name_row_map = build_name_row_map(sheet)

    updates = []
    written = 0
    skipped = []

    for norm_name, total_cases in rows:
        row = name_row_map.get(norm_name)
        if row is None:
            skipped.append(norm_name)
            continue

        updates.append({
            "range": rowcol_to_a1(row, case_col),
            "values": [[total_cases]]
        })
        written += 1

    if updates:
        sheet.batch_update(updates)

    return written, skipped

@bot.command()
@is_pbt()
async def sync(ctx, date_str: str):
    try:
        target_date = parse_date_smart(date_str)
    except:
        await ctx.send("❌ ใช้ `!sync DD/MM/YYYY`")
        return

    await ctx.send("⏳ กำลังเขียนข้อมูลลง Google Sheet...")

    try:
        written, skipped = await asyncio.to_thread(
            run_daily_case_sync,
            target_date
        )
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")
        return

    embed = Embed(
        title="📊 เขียนข้อมูลลง Google Sheet",
        description=f"📅 วันที่: {target_date.strftime('%d/%m/%Y')}",
        color=0x2ecc71
    )
    embed.add_field(
        name="✅ เขียนสำเร็จ",
        value=f"{written} คน",
        inline=False
    )

    if skipped:
        embed.add_field(
            name="⚠️ ไม่พบชื่อในชีท",
            value="\n".join(skipped),
            inline=False
        )

    embed.set_footer(text="เขียนลง Google Sheet เรียบร้อย")
    await ctx.send(embed=embed)

async def count_body_cases_split(work_date):
    start, end = get_body_work_window(work_date)

    chub = 0
    wrap = 0

    chub_channel = bot.get_channel(BODY_CHUB_CHANNEL_ID)
    if chub_channel:
        async for msg in chub_channel.history(after=start, before=end, limit=2000):
            if not msg.author.bot:
                chub += 1

    wrap_channel = bot.get_channel(BODY_WRAP_CHANNEL_ID)
    if wrap_channel:
        async for msg in wrap_channel.history(after=start, before=end, limit=2000):
            if not msg.author.bot:
                wrap += 1

    total = chub + wrap

    return {
        "date": work_date,
        "start": start,
        "end": end,
        "chub": chub,
        "wrap": wrap,
        "total": total
    }


@bot.command()
@is_pbt()
async def testbody(ctx, date_str: str):
    print("🔥 testbody CALLED")
    try:
        target_date = parse_date_smart(date_str)
    except:
        await ctx.send("❌ ใช้ `!testbody DD/MM/YYYY`")
        return

    result = await count_body_cases_split(target_date)

    # ✅ SAVE DB
    save_body_case_daily_split(result)

    await ctx.send(
        "🧪 Body Case Test (Split)\n"
        f"📅 {result['date']}\n"
        f"⏰ {result['start'].strftime('%H:%M')} → {result['end'].strftime('%H:%M')}\n"
        f"🧪 ชุบ: {result['chub']} เคส\n"
        f"🧳 ช่วยอุ้ม/ห่อ: {result['wrap']} เคส\n"
        f"📦 รวมทั้งหมด: {result['total']} เคส\n"
        f"💾 บันทึกลง DB แล้ว"
    )

@bot.command()
@is_pbt()  # ให้เฉพาะ ผบตร. ใช้ กันสแปม
async def testmail(ctx):
    await ctx.send("📧 กำลังทดสอบส่งอีเมลแจ้งเตือน...")

    try:
        send_email_alert(
            subject="🧪 TEST EMAIL - Police Bot",
            body=(
                "This is a test email from Railway Police Bot.\n\n"
                "If you receive this email:\n"
                "- Email system: OK\n"
                "- Resend API: OK\n"
                "- Environment Variables: OK\n\n"
                "Time: " + now_th().strftime("%d/%m/%Y %H:%M:%S")
            )
        )

        await ctx.send("✅ ส่งอีเมลทดสอบแล้ว (เช็คกล่องเมล)")

    except Exception as e:
        await ctx.send(f"❌ ส่งเมลล้มเหลว: `{e}`")

@bot.command()
@is_pbt()
async def bodytest(ctx, date_str: str = None):
    # 1️⃣ เลือกวันที่
    if date_str:
        try:
            work_date = parse_date_smart(date_str)
        except:
            await ctx.send("❌ ใช้ `!bodytest DD/MM[/YYYY]`")
            return
    else:
        work_date = today_th() - timedelta(days=1)

    await ctx.send("🧪 กำลังทดสอบ Body Case (Manual mode)...")

    # 2️⃣ นับเคส
    result = await count_body_cases_split(work_date)

    # 3️⃣ เขียน DB
    save_body_case_daily_split(result)

    # 4️⃣ เขียน Google Sheet
    write_body_case_total(
        work_date,
        result["total"]
    )

    # 5️⃣ สร้าง embed
    embed = build_body_dashboard_embed(result, work_date)

    embed.set_footer(
        text=f"🧪 Manual test • {now_th().strftime('%d/%m/%Y %H:%M')}"
    )

    # 6️⃣ ส่ง / แก้ dashboard
    channel = bot.get_channel(BODY_DASHBOARD_CHANNEL_ID)
    msg_id = get_body_dashboard_message_id()

    try:
        if msg_id:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed)
            await ctx.send("🔄 แก้ไข Dashboard เดิมเรียบร้อย")
        else:
            msg = await channel.send(embed=embed)
            await msg.pin()
            set_body_dashboard_message_id(msg.id)
            await ctx.send("🆕 สร้าง Dashboard ใหม่เรียบร้อย")

    except Exception as e:
        await ctx.send(f"❌ Dashboard error: `{e}`")


#@bot.command()
#async def audit(ctx, limit: int = 10):
#    limit = max(1, min(limit, 20))
#
#    with get_conn() as conn:
#        with conn.cursor() as cur:
#            cur.execute("""
#                SELECT action, actor, target, channel, message_id, detail, created_at
#                FROM audit_logs
#                ORDER BY created_at DESC
#                LIMIT %s
#            """, (limit,))
#            rows = cur.fetchall()
#
#    if not rows:
#        await ctx.send("📭 ยังไม่มี audit log")
#        return
#
#    embed = Embed(
#        title="🧾 Audit Log",
#        description=f"แสดง {len(rows)} รายการล่าสุด",
#        color=0xe67e22
#    )
#
#    for action, actor, target, channel, msg_id, detail, created in rows:
#        time_str = created.astimezone(TH_TZ).strftime("%d/%m %H:%M")
#        embed.add_field(
#            name=f"🔹 {action}",
#            value=(
#                f"👤 {actor or '-'}\n"
#                f"🎯 {target or '-'}\n"
#                f"📍 {channel or '-'}\n"
#                f"🆔 `{msg_id or '-'}`\n"
#                f"📝 {detail or '-'}\n"
#                f"🕒 {time_str}"
#            ),
#            inline=False
#        )
#
#    await ctx.send(embed=embed)

# ======================
# CMD HELP (สำคัญ)
# ======================
@bot.command()
async def cmd(ctx):
    embed = Embed(
        title="📖 Case Bot — คำสั่งที่ใช้งานได้",
        description=(
            "บอทสำหรับบันทึกและสรุปคดี\n"
            "• รายบุคคล = แสดงเป็น **เคส**\n"
            "• ภาพรวม = นับเป็น **คดี (โพสลง Discord)**\n\n"
            "📅 รูปแบบวันที่:\n"
            "• `DD/MM` = ปีปัจจุบัน (ถ้าวันอยู่อนาคต จะถอยไปปีที่แล้วอัตโนมัติ)\n"
            "• `DD/MM/YYYY` = ระบุปีตรง ๆ"
        ),
        color=0x3498db
    )

    # ===== คำสั่งสรุปภาพรวม =====
    embed.add_field(
        name="📊 สรุปภาพรวม",
        value=(
            "`!today` — สรุปคดีวันนี้ (รายคน / แยกปกติ-จุด10)\n"
            "`!week` — สรุปคดีประจำสัปดาห์ (รายคน)\n"
            "`!posts` — 🧮 รวมจำนวนคดีที่ลง (วันนี้ + สัปดาห์)\n"
            "  ↳ นับเฉพาะ **โพส** (แท็กซ้ำไม่นับ)"
        ),
        inline=False
    )

    # ===== คำสั่งรายบุคคล =====
    embed.add_field(
        name="👤 คำสั่งรายบุคคล",
        value=(
            "`!me` — ดูคดีของตัวเองวันนี้\n"
            "`!check ชื่อ` — 🔍 เช็กคดีของบุคคล (วันนี้)\n"
            "`!checkdate DD/MM[/YYYY] ชื่อ` — 🔍 เช็กคดีย้อนหลังรายบุคคล"
        ),
        inline=False
    )

    # ===== คำสั่งตามวันที่ =====
    embed.add_field(
        name="📅 คำสั่งตามวันที่",
        value="`!date DD/MM[/YYYY]` — ดูคดีทั้งหมดตามวันที่",
        inline=False
    )

    # ===== เครื่องมือ =====
    embed.add_field(
        name="🛠️ เครื่องมือ",
        value=(
            "`!time` — ⏰ ตรวจเวลาของบอท (TH / UTC+7)\n"
            "`!sync DD/MM[/YYYY]` — 📊 เขียนจำนวนเคสลง Google Sheet\n"
            "`!cmd` — 📖 ดูคำสั่งทั้งหมด"
        ),
        inline=False
    )
# ===== คำสั่งคดีขึ้นเขา =====
    embed.add_field(
        name="🏔️ คำสั่งคดีขึ้นเขา",
        value=(
           "`!checkuphill` — ดูคดีขึ้นเขาวันนี้ทั้งหมด\n"
           "`!checkuphill ชื่อ` — ดูคดีขึ้นเขาวันนี้ (เฉพาะบุคคล)\n"
           "`!checkuphill DD/MM` — ดูคดีขึ้นเขาตามวันที่\n"
           "`!checkuphill DD/MM[/YYYY] ชื่อ` — ดูคดีขึ้นเขาตามวันที่ (เฉพาะบุคคล)"
     ),
     inline=False
    )

    # ===== Audit / Admin =====
    if any(role.id == PBT_ROLE_ID for role in ctx.author.roles):
        embed.add_field(
            name="🧾 Audit / ตรวจสอบระบบ (ผบตร.)",
            value=(
                "`!audit person` — ตรวจสอบการแท็กชื่อซ้ำในโพสเดียวกัน\n"
                "`!audit export DD/MM/YYYY` — export audit log (CSV + Excel)\n"
                "`!audit export DD/MM/YYYY DD/MM/YYYY` — export audit log ตามช่วงวัน (CSV + Excel)\n"
                "`!audit export csv DD/MM/YYYY [DD/MM/YYYY]` — export เฉพาะ CSV\n"
                "`!audit export excel DD/MM/YYYY [DD/MM/YYYY]` — export เฉพาะ Excel\n"
                "  ↳ ใช้ได้เฉพาะห้อง **audit**"
            ),
            inline=False
        )

        embed.add_field(
            name="🛑 คำสั่งผู้บังคับบัญชา (ผบตร.)",
            value=(
                "`!resetdb` — 🧨 ลบข้อมูลคดีทั้งหมด\n"
                "`!confirm <password>` — ยืนยันการลบข้อมูล"
            ),
            inline=False
        )

    embed.set_footer(text=SYSTEM_FOOTER)
    await ctx.send(embed=embed)

# ⚠️ EMERGENCY COMMAND
# ใช้เฉพาะกรณีข้อมูลพัง / rebuild ย้อนหลัง
# ห้ามใช้ปกติ
@bot.command()
@is_pbt()
async def rebuilddate(ctx, date_str: str):

    if not EMERGENCY_REBUILD_ENABLED:
        await ctx.send(
            "🔒 คำสั่งนี้ถูกปิดตามนโยบายระบบ\n"
            "ใช้เฉพาะกรณีฉุกเฉินเท่านั้น"
        )
        return
    try:
        d, m, y = map(int, date_str.split("/"))
        start = datetime(y, m, d, 0, 0, 0, tzinfo=TH_TZ)
        end = start + timedelta(days=1)
    except:
        await ctx.send("❌ ใช้ `!rebuilddate DD/MM/YYYY`")
        return

    await ctx.send(
        f"🔄 เริ่ม rebuild วันที่ {date_str}\n"
        "⛔ กรุณางดลงคดีระหว่างกระบวนการนี้"
    )

    rebuilt = 0

    for channel_id in [CASE10_CHANNEL_ID, *NORMAL_CHANNEL_IDS]:
        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        async for msg in channel.history(
            after=start,
            before=end,
            limit=None
        ):
            if msg.author.bot:
                continue
            if not msg.mentions:
                continue

            tasks = []

            for member in set(msg.mentions):
                uphill = is_uphill_case(msg.content)
                tasks.append(
                    save_case_async(
                        member.display_name,
                        msg.channel.name,
                        "case10" if msg.channel.id == CASE10_CHANNEL_ID else "normal",
                        2 if msg.channel.id == CASE10_CHANNEL_ID else 1,
                        msg.id,
                        msg.created_at.astimezone(TH_TZ).date(),
                        uphill
                    )
                )

            await asyncio.gather(*tasks)
            rebuilt += 1

    write_audit(
        action="REBUILD_DATE",
        actor=ctx.author.display_name,
        detail=date_str
    )

    await ctx.send(
        f"✅ rebuild เสร็จแล้ว\n"
        f"📊 ประมวลผล {rebuilt} โพส"
    )

# ======================
# RESET DB
# ======================
pending_reset = set()

@bot.command()
@is_pbt()
async def resetdb(ctx):
    pending_reset.add(ctx.author.id)
    await ctx.send(
        "⚠️ จะลบข้อมูลทั้งหมด\n"
        f"พิมพ์ `!confirm {RESET_PASSWORD}`"
    )

@bot.command()
@is_pbt()
async def confirm(ctx, password: str):
    if ctx.author.id not in pending_reset:
        return

    if password != RESET_PASSWORD:
        await ctx.send("❌ รหัสผิด")
        return

    pending_reset.remove(ctx.author.id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE cases RESTART IDENTITY;")
    write_audit(
    action="RESET_DB",
    actor=ctx.author.display_name,
    detail="truncate cases"
    )
   
    await ctx.send("🧨 ลบข้อมูลเรียบร้อย")

@bot.command()
@is_pbt()
async def bodydash(ctx, date_str: str = None):
    # ถ้าไม่ใส่วันที่ → ใช้เมื่อวาน
    if date_str:
        work_date = parse_date_smart(date_str)
    else:
        work_date = today_th() - timedelta(days=1)

    embed = Embed(
        title="🧾 Body Case Dashboard",
        description=(
            f"📅 วันที่ปฏิบัติงาน: {work_date}\n"
            f"⏰ ช่วงเวลา: 06:00 → 05:59\n\n"
            f"⌛ รอระบบ Auto-sync เวลา 06:05"
        ),
        color=0xe67e22
    )

    embed.set_footer(
        text="🔄 Dashboard ถูกสร้างแล้ว • Auto-sync เวลา 06:05"
    )

    msg = await ctx.send(embed=embed)
    await msg.pin()
    set_body_dashboard_message_id(msg.id)


# ======================
# REGISTER AUDIT COMMANDS
# ======================
setup_audit_commands(bot, get_conn, is_pbt)   
# ======================
# RUN
# ======================
bot.run(TOKEN)
