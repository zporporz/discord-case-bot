# ======================
# IMPORTS
# ======================
import os
import re
import discord
import psycopg2
from datetime import datetime, timedelta
from discord.ext import commands


# ======================
# ENV / CONSTANTS
# ======================
TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

PBT_ROLE_ID = 1393537553264545922   # 👮 ผบตร.
RESET_PASSWORD = "GRPL2025"   # 🔐 รหัสยืนยัน resetdb

CASE10_CHANNEL_ID = 1443212808316780654
NORMAL_CHANNEL_IDS = [
    1393542799617691658,
    1400477664900288576
]


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


def save_case_pg(name, channel, case_type, cases, message_id):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO cases (date, name, channel, case_type, cases, message_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (message_id, name) DO NOTHING
                """, (
                    datetime.now().date(),
                    name,
                    channel,
                    case_type,
                    cases,
                    str(message_id)
                ))
        print(f"✅ Saved: {name} [{case_type}] +{cases}")
    except Exception as e:
        print("❌ DB error:", e)


# ======================
# UTILS
# ======================
def normalize_name(name: str):
    name = re.sub(r"\+?\d+\s*", "", name)
    name = re.sub(r"\[.*?\]\s*", "", name)
    return name.strip().lower()


def get_week_range_sun_sat():
    today = datetime.now().date()
    start = today - timedelta(days=(today.weekday() + 1) % 7)
    end = start + timedelta(days=6)
    return start, end


# ======================
# DISCORD SETUP
# ======================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ======================
# EVENTS
# ======================
@bot.event
async def on_ready():
    print(f"🤖 บอทออนไลน์แล้ว: {bot.user}")


@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author.bot or not message.mentions:
        return

    if message.channel.id == CASE10_CHANNEL_ID:
        case_type = "case10"
        case_value = 2
    elif message.channel.id in NORMAL_CHANNEL_IDS:
        case_type = "normal"
        case_value = 1
    else:
        return

    for member in message.mentions:
        save_case_pg(
            member.display_name,
            message.channel.name,
            case_type,
            case_value,
            message.id
        )


# ======================
# COMMANDS
# ======================
@bot.command()
async def today(ctx):
    today = datetime.now().date()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*), SUM(cases)
                FROM cases
                WHERE date = %s
                GROUP BY name, case_type
                ORDER BY name
            """, (today,))
            rows = cur.fetchall()

    if not rows:
        await ctx.send("วันนี้ยังไม่มีคดี")
        return

    normal, case10 = {}, {}

    for name, ctype, inc, total in rows:
        target = normal if ctype == "normal" else case10
        target[name] = (inc, total)

    msg = "📊 **สรุปคดีวันนี้**\n\n"

    if normal:
        msg += "🟦 **คดีปกติ**\n"
        for n, (i, t) in normal.items():
            msg += f"- {n}: {i} คดี ({t} เคส)\n"
        msg += "\n"

    if case10:
        msg += "🟥 **คดีจุด 10**\n"
        for n, (i, t) in case10.items():
            msg += f"- {n}: {i} คดี ({t} เคส)\n"

    await ctx.send(msg)


@bot.command()
async def me(ctx):
    today = datetime.now().date()
    name = ctx.author.display_name

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT case_type, COUNT(*), COALESCE(SUM(cases),0)
                FROM cases
                WHERE date = %s AND name = %s
                GROUP BY case_type
            """, (today, name))
            rows = cur.fetchall()

    if not rows:
        await ctx.send("วันนี้คุณยังไม่มีคดี")
        return

    msg = f"👮 **{name} วันนี้**\n"

    for ctype, inc, total in rows:
        label = "คดีปกติ" if ctype == "normal" else "คดีจุด 10"
        msg += f"- {label}: {inc} คดี ({total} เคส)\n"

    await ctx.send(msg)

@bot.command()
async def date(ctx, date_str: str):
    try:
        d, m = map(int, date_str.split("/"))
        y = datetime.now().year
        target = datetime(y, m, d).date()
    except:
        await ctx.send("❌ ใช้ `!date DD/MM`")
        return

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*), SUM(cases)
                FROM cases
                WHERE date = %s
                GROUP BY name, case_type
                ORDER BY name
            """, (target,))
            rows = cur.fetchall()

    if not rows:
        await ctx.send(f"📅 วันที่ {date_str} ไม่มีคดี")
        return

    normal, case10 = {}, {}

    for name, ctype, inc, total in rows:
        target_map = normal if ctype == "normal" else case10
        target_map[name] = (inc, total)

    msg = f"📊 **สรุปคดีวันที่ {date_str}**\n\n"

    if normal:
        msg += "🟦 **คดีปกติ**\n"
        for n,(i,t) in normal.items():
            msg += f"- {n}: {i} คดี ({t} เคส)\n"
        msg += "\n"

    if case10:
        msg += "🟥 **คดีจุด 10**\n"
        for n,(i,t) in case10.items():
            msg += f"- {n}: {i} คดี ({t} เคส)\n"

    await ctx.send(msg)


@bot.command()
async def week(ctx):
    start, end = get_week_range_sun_sat()

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, SUM(cases)
                FROM cases
                WHERE date BETWEEN %s AND %s
                GROUP BY name, case_type
                ORDER BY SUM(cases) DESC
            """, (start, end))
            rows = cur.fetchall()

    if not rows:
        await ctx.send("ไม่มีข้อมูลในสัปดาห์นี้")
        return

    normal, case10 = {}, {}

    for name, ctype, total in rows:
        target = normal if ctype == "normal" else case10
        target[name] = total

    msg = f"📆 **สรุปสัปดาห์ ({start} → {end})**\n\n"

    if normal:
        msg += "🟦 **คดีปกติ**\n"
        for n,t in normal.items():
            msg += f"- {n}: {t} เคส\n"
        msg += "\n"

    if case10:
        msg += "🟥 **คดีจุด 10**\n"
        for n,t in case10.items():
            msg += f"- {n}: {t} เคส\n"

    await ctx.send(msg)
    
@bot.command()
async def cmd(ctx, section: str = None):
    # ======================
    # CMD ทั่วไป
    # ======================
    if section is None:
        msg = (
            "📖 **คำสั่งบอทนับคดี**\n\n"
            "👮 **คำสั่งทั่วไป**\n"
            "`!today` — สรุปคดีวันนี้ (แยกคดีปกติ / จุด 10)\n"
            "`!me` — ดูคดีของตัวเองวันนี้ (แยกประเภท)\n"
            "`!date DD/MM` — ดูคดีย้อนหลังตามวันที่\n"
            "`!week` — สรุปคดีประจำสัปดาห์ (อาทิตย์–เสาร์)\n\n"
            "🛠️ พิมพ์ `!cmd admin` สำหรับคำสั่งผู้บังคับบัญชา"
        )
        await ctx.send(msg)
        return

    # ======================
    # CMD ADMIN (ผบตร.)
    # ======================
    if section.lower() == "admin":
        if not any(role.id == PBT_ROLE_ID for role in ctx.author.roles):
            await ctx.send("⛔ คำสั่งนี้ใช้ได้เฉพาะ **ผบตร.** เท่านั้น")
            return

        msg = (
            "🛑 **คำสั่งผู้บังคับบัญชา (ผบตร.)**\n\n"
            "`!resetdb` — 🧨 ลบข้อมูลคดีทั้งหมดในฐานข้อมูล PostgreSQL\n\n"
            "⚠️ คำสั่งนี้ต้องยืนยันรหัสผ่าน"
        )
        await ctx.send(msg)
        return

    # ======================
    # CMD ไม่รู้จัก
    # ======================
    await ctx.send("❓ ไม่พบหมวดคำสั่งนี้ ใช้ `!cmd` หรือ `!cmd admin`")
    

# ======================
# RESET DB (CONFIRM)
# ======================
pending_reset = set()

@bot.command()
@is_pbt()
async def resetdb(ctx):
    pending_reset.add(ctx.author.id)
    await ctx.send(
        "⚠️ **คำเตือน:** จะลบข้อมูลทั้งหมดในฐานข้อมูล\n"
        f"พิมพ์ `!confirm {RESET_PASSWORD}` เพื่อยืนยัน"
    )


@bot.command()
@is_pbt()
async def confirm(ctx, password: str):
    if ctx.author.id not in pending_reset:
        await ctx.send("❌ ไม่มีรายการ reset ที่รอการยืนยัน")
        return

    if password != RESET_PASSWORD:
        await ctx.send("❌ รหัสยืนยันไม่ถูกต้อง")
        return

    pending_reset.remove(ctx.author.id)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE cases RESTART IDENTITY;")
        await ctx.send("🧨 **ลบข้อมูลในฐานข้อมูลทั้งหมดเรียบร้อยแล้ว**")
    except Exception as e:
        print(e)
        await ctx.send("❌ Reset DB ไม่สำเร็จ")


# ======================
# RUN
# ======================
bot.run(TOKEN)
