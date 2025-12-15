# ======================
# IMPORTS
# ======================
import os
import re
import discord
import psycopg2
from datetime import datetime, timedelta
from discord.ext import commands
from audit.audit_commands import setup_audit_commands
from discord import Embed
from datetime import timezone
ALLOWED_COMMAND_CHANNEL_ID = 1449425399397482789


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
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)


def save_case_pg(
    name: str,
    channel: str,
    case_type: str,
    cases: int,
    message_id: int,
    message_date
):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO cases
                        (date, name, channel, case_type, cases, message_id)
                    VALUES
                        (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (message_id, name) DO NOTHING
                """, (
                    message_date,
                    name,
                    channel,
                    case_type,
                    cases,
                    str(message_id)
                ))
        print(
            f"✅ Saved | {name} | {case_type} | +{cases} | "
            f"date={message_date} | msg={message_id}"
        )
    except Exception as e:
        print("❌ DB error:", e)

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

# ======================
# UTILS
# ======================
def normalize_name(name: str):
    name = re.sub(r"\+?\d+\s*", "", name)
    name = re.sub(r"\[.*?\]\s*", "", name)
    return name.strip().lower()


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
    unique_members = set(message.mentions)

    for member in unique_members:
        save_case_pg(
            member.display_name,
            message.channel.name,
            case_type,
            case_value,
            message.id,
            message_date
        )

def now_th():
    return datetime.now(TH_TZ)

def today_th():
    return now_th().date()

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

    # อนุญาตเฉพาะห้องที่กำหนด
    if ctx.channel.id != ALLOWED_COMMAND_CHANNEL_ID:
        return False

    return True

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send(
            "❌ ใช้คำสั่งบอทได้เฉพาะห้องที่กำหนดเท่านั้น",
            delete_after=5
        )

# ======================
# EVENTS
# ======================
@bot.event
async def on_ready():
    print(f"🤖 Bot online: {bot.user}")
    await backfill_recent_cases()

async def backfill_recent_cases(limit_per_channel=50):
    print("🔄 Backfill started")

    last_online = get_last_online()
    now = now_th()

    for channel_id in [CASE10_CHANNEL_ID, *NORMAL_CHANNEL_IDS]:
        channel = bot.get_channel(channel_id)
        if not channel:
            continue

        async for msg in channel.history(limit=limit_per_channel):
            if msg.author.bot or not msg.mentions:
                continue

            # 👉 ถ้ามี last_online ใช้แบบเวลา
            if last_online and msg.created_at.astimezone(TH_TZ) <= last_online:
                continue

            if is_message_saved(msg.id):
                continue

            process_case_message(msg)

            print(
                f"🧩 Backfilled | "
                f"msg={msg.id} | "
                f"channel={channel.name}"
            )

    # ✅ update เวลา หลัง backfill เสร็จ
    set_last_online(now_th())

    print("✅ Backfill finished")

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

    mentions = message.mentions
    unique_members = set(mentions)

    if len(mentions) != len(unique_members):
        print(
            f"⚠️ Duplicate mention detected | "
            f"msg={message.id} | "
            f"{len(mentions)} → {len(unique_members)}"
        )

    for member in unique_members:
        save_case_pg(
            member.display_name,
            message.channel.name,
            case_type,
            case_value,
            message.id,
            message_date
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
            # audit log จะอ้างถึง "คนที่โดนลบข้อความ"
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
                    "DELETE FROM cases WHERE message_id = %s",
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

    except Exception as e:
        print("❌ DB delete error:", e)

@bot.event
async def on_message_edit(before, after):
    # สนใจเฉพาะห้องคดี
    if after.channel.id not in [CASE10_CHANNEL_ID, *NORMAL_CHANNEL_IDS]:
        return

    if after.author.bot:
        return

    # ใช้เวลาไทย
    if after.created_at.astimezone(TH_TZ).date() != today_th():
        print(f"⛔ Ignore edit (old message) | msg={after.id}")
        return

    print(f"✏️ Message edited | msg={after.id}")

    # 1️⃣ ลบเคสเดิมทั้งหมดของ message นี้
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM cases WHERE message_id = %s",
                    (str(after.id),)
                )
                deleted = cur.rowcount
        print(f"🗑️ Deleted {deleted} old cases | msg={after.id}")
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
    unique_members = set(after.mentions)

    for member in unique_members:
        save_case_pg(
            member.display_name,
            after.channel.name,
            case_type,
            case_value,
            after.id,
            message_date
        )

    print(f"✅ Recounted cases | msg={after.id}")

# ======================
# COMMANDS
# ======================

@bot.command()
async def today(ctx):
    today = today_th()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*) AS inc, SUM(cases) AS total
                FROM cases
                WHERE date = %s
                GROUP BY name, case_type
            """, (today,))
            rows = cur.fetchall()

    if not rows:
        await ctx.send(embed=Embed(
            description="📭 วันนี้ยังไม่มีคดี",
            color=0x2f3136
        ))
        return

    embed = Embed(
        title="📊 Case Summary — Today",
        description=f"📅 วันที่: {today.strftime('%d/%m/%Y')}",
        color=0x2ecc71
    )

    summary = {}

    # ✅ footer = คดี (โพส)
    total_posts_all = 0
    total_normal_posts = 0
    total_point10_posts = 0

    for name, ctype, inc, total in rows:
        if name not in summary:
            summary[name] = {
                "normal_cases": 0,
                "normal_posts": 0,
                "point10_cases": 0,
                "point10_posts": 0
            }

        if ctype == "normal":
            summary[name]["normal_cases"] += total        # เคส
            summary[name]["normal_posts"] += inc          # คดี
            total_normal_posts += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc
            total_point10_posts += inc

        total_posts_all += inc   # ❗ นับโพสเท่านั้น

    # ===== แสดงรายคน (ยังเป็นเคส) =====
    for name, data in summary.items():
        value = ""

        if data["normal_cases"] > 0:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"

        if data["point10_cases"] > 0:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)\n"

        total_person = data["normal_cases"] + data["point10_cases"]
        value += f"📊 **รวมทั้งหมด: {total_person} เคส**"

        embed.add_field(
            name=f"👤 {name}",
            value=value,
            inline=False
        )

    # ===== footer = คดี (โพส) =====
    embed.set_footer(text=(
        f"📊 รวมทั้งหมดทั้งระบบ: {total_posts_all} คดี\n"
        f"📂 คดีปกติ: {total_normal_posts} คดี | "
        f"🚨 คดีจุด 10: {total_point10_posts} คดี\n"
        f"🔒 ระบบป้องกันการนับซ้ำอัตโนมัติ"
    ))

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
                WHERE date = %s AND name = %s
                GROUP BY case_type
            """, (today, name))
            rows = cur.fetchall()

    if not rows:
        await ctx.send(embed=Embed(
            description="📭 วันนี้คุณยังไม่มีคดี",
            color=0x2f3136
        ))
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

    embed.set_footer(text=(
        f"📊 รวมทั้งหมด: {total_posts_all} คดี\n"
        f"📂 คดีปกติ: {total_normal_posts} คดี | "
        f"🚨 คดีจุด 10: {total_point10_posts} คดี"
    ))

    await ctx.send(embed=embed)

@@bot.command()
async def date(ctx, date_str: str):
    try:
        d, m = map(int, date_str.split("/"))
        y = now_th().year
        target = datetime(y, m, d, tzinfo=TH_TZ).date()
    except:
        await ctx.send("❌ ใช้ `!date DD/MM`")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*) AS inc, SUM(cases) AS total
                FROM cases
                WHERE date = %s
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

    for name, data in summary.items():
        value = ""
        if data["normal_cases"]:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"]:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)\n"

        value += f"📊 **รวมทั้งหมด: {data['normal_cases'] + data['point10_cases']} เคส**"
        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    embed.set_footer(text=(
        f"📊 รวมทั้งหมดทั้งระบบ: {total_posts_all} คดี\n"
        f"📂 คดีปกติ: {total_normal_posts} คดี | "
        f"🚨 คดีจุด 10: {total_point10_posts} คดี"
    ))

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

    for name, data in summary.items():
        value = ""
        if data["normal_cases"]:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"]:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)\n"

        value += f"📊 **รวมทั้งหมด: {data['normal_cases'] + data['point10_cases']} เคส**"
        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    embed.set_footer(text=(
        f"📊 รวมทั้งหมดทั้งระบบ: {total_posts_all} คดี\n"
        f"📂 คดีปกติ: {total_normal_posts} คดี | "
        f"🚨 คดีจุด 10: {total_point10_posts} คดี"
    ))

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
                WHERE date = %s AND name ILIKE %s
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
            total_normal_posts += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc
            total_point10_posts += inc

        total_posts_all += inc

    for name, data in summary.items():
        value = ""
        if data["normal_cases"]:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"]:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)"

        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    embed.set_footer(text=(
        f"📊 รวมทั้งหมด: {total_posts_all} คดี | "
        f"📂 {total_normal_posts} | 🚨 {total_point10_posts}"
    ))

    await ctx.send(embed=embed)

@bot.command()
async def checkdate(ctx, date_str: str, *, keyword: str):
    try:
        d, m = map(int, date_str.split("/"))
        y = now_th().year
        target = datetime(y, m, d, tzinfo=TH_TZ).date()
    except:
        await ctx.send("❌ ใช้ `!checkdate DD/MM ชื่อ`")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*) AS inc, SUM(cases) AS total
                FROM cases
                WHERE date = %s AND name ILIKE %s
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
            total_normal_posts += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc
            total_point10_posts += inc

        total_posts_all += inc

    for name, data in summary.items():
        value = ""
        if data["normal_cases"]:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"]:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)"

        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    embed.set_footer(text=(
        f"📊 รวมทั้งหมด: {total_posts_all} คดี | "
        f"📂 {total_normal_posts} | 🚨 {

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
    await ctx.send(embed=embed)

# ======================
# CMD HELP (สำคัญ)
# ======================
@bot.command()
async def cmd(ctx):
    embed = Embed(
        title="📖 Case Bot — คำสั่งที่ใช้งานได้",
        description="บอทสำหรับสรุปคดีปกติ และคดีจุด 10",
        color=0x3498db
    )

    # ===== คำสั่งทั่วไป =====
    embed.add_field(
        name="👮 คำสั่งทั่วไป",
        value=(
            "`!today` — สรุปคดีวันนี้ (แยกคดีปกติ / จุด 10)\n"
            "`!me` — ดูคดีของตัวเองวันนี้\n"
            "`!date DD/MM` — ดูคดีย้อนหลังตามวันที่ (ทุกคน)\n"
            "`!week` — สรุปคดีประจำสัปดาห์ (อาทิตย์–เสาร์)\n"
            "`!check ชื่อ` — 🔍 เช็กคดีของบุคคล (วันนี้)\n"
            "`!checkdate DD/MM ชื่อ` — 🔍 เช็กคดีย้อนหลังรายบุคคล \n"
            "`!time` — 🔍 ตรวจเวลาของบอท"
        ),
        inline=False
    )

    # ===== คำสั่งแอดมิน =====
    if any(role.id == PBT_ROLE_ID for role in ctx.author.roles):
        embed.add_field(
            name="🛑 คำสั่งผู้บังคับบัญชา (ผบตร.)",
            value=(
                "`!resetdb` — 🧨 ลบข้อมูลคดีทั้งหมด\n"
                "`!confirm <password>` — ยืนยันการลบข้อมูล"
            ),
            inline=False
        )

    await ctx.send(embed=embed)


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

    await ctx.send("🧨 ลบข้อมูลเรียบร้อย")
# ======================
# REGISTER AUDIT COMMANDS
# ======================
setup_audit_commands(bot, get_conn, is_pbt)
# ======================
# RUN
# ======================
bot.run(TOKEN)
