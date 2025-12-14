import os
import re
import discord
import psycopg2
from datetime import datetime, timedelta
from discord.ext import commands


# ======================
# PERMISSION CHECK  
# ======================
def is_pbt():
    async def predicate(ctx):
        return any(role.id == PBT_ROLE_ID for role in ctx.author.roles)
    return commands.check(predicate)
# ======================
# Database
# ======================
DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("DISCORD_TOKEN")

def get_conn():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(db_url)

def save_case_pg(name, channel, case_type, cases, message_id):
    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        print("❌ DATABASE_URL not found")
        return

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO cases (date, name, channel, case_type, cases, message_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (message_id) DO NOTHING
        """, (
            datetime.now().strftime("%Y-%m-%d"),
            name,
            channel,
            case_type,   # 👈 เพิ่มตรงนี้
            cases,
            str(message_id)
        ))

        conn.commit()
        cur.close()
        conn.close()

        print(f"✅ Saved to DB: {name} [{case_type}] +{cases}")

    except Exception as e:
        print("❌ DB error:", e)

# ======================
# Utils
# ======================
def normalize_name(name: str):
    name = re.sub(r"\+?\d+\s*", "", name)
    name = re.sub(r"\[.*?\]\s*", "", name)
    return name.strip().lower()

def get_week_range_sun_sat():
    today = datetime.now()
    start = today - timedelta(days=(today.weekday() + 1) % 7)
    end = start + timedelta(days=6)
    return start.date(), end.date()

# ======================
# Discord
# ======================
CASE10_CHANNEL_ID = 1443212808316780654
NORMAL_CHANNEL_IDS = [
    1393542799617691658,
    1400477664900288576
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🤖 บอทออนไลน์แล้ว: {bot.user}")

@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author.bot:
        return
    if not message.mentions:
        return

    if message.channel.id == CASE10_CHANNEL_ID:
        case_value = 2
        case_type = "case10"
    elif message.channel.id in NORMAL_CHANNEL_IDS:
        case_value = 1
        case_type = "normal"
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
# Commands
# ======================
@bot.command()
async def today(ctx):
    db_url = os.getenv("DATABASE_URL")
    today = datetime.now().date()

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    cur.execute("""
        SELECT name, case_type, COUNT(*) AS incidents, SUM(cases) AS total_cases
        FROM cases
        WHERE date = %s
        GROUP BY name, case_type
        ORDER BY name
    """, (today,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

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
        for n,(i,t) in normal.items():
            msg += f"- {n}: {i} คดี ({t} เคส)\n"
        msg += "\n"

    if case10:
        msg += "🟥 **คดีจุด 10**\n"
        for n,(i,t) in case10.items():
            msg += f"- {n}: {i} คดี ({t} เคส)\n"

    await ctx.send(msg)

@bot.command()
async def me(ctx):
    today = datetime.now().date()
    name = ctx.author.display_name

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*), COALESCE(SUM(cases),0)
                FROM cases
                WHERE date = %s AND name = %s
            """, (today, name))
            incidents, cases = cur.fetchone()

    if incidents == 0:
        await ctx.send("วันนี้คุณยังไม่มีคดี")
        return

    await ctx.send(f"👮 {name}\nวันนี้ทำ {incidents} คดี ({cases} เคส)")
    
@bot.command()
async def date(ctx, date_str: str):
    try:
        parts = date_str.split("/")
        if len(parts) == 2:
            day, month = map(int, parts)
            year = datetime.now().year
        elif len(parts) == 3:
            day, month, year = map(int, parts)
        else:
            raise ValueError

        target_date = datetime(year, month, day).date()
    except:
        await ctx.send("❌ รูปแบบวันที่ไม่ถูกต้อง ใช้ `!date DD/MM` หรือ `!date DD/MM/YYYY`")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, SUM(cases), COUNT(*)
                FROM cases
                WHERE date = %s
                GROUP BY name
            """, (target_date,))
            rows = cur.fetchall()

    if not rows:
        await ctx.send(f"📅 วันที่ {date_str} ไม่มีคดี")
        return

    msg = f"📊 **สรุปคดีวันที่ {date_str}**\n"
    for name, cases, incidents in sorted(rows, key=lambda x: normalize_name(x[0])):
        msg += f"- {name}: {incidents} คดี ({cases} เคส)\n"

    await ctx.send(msg)


@bot.command()
async def week(ctx):
    start, end = get_week_range_sun_sat()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, SUM(cases)
                FROM cases
                WHERE date BETWEEN %s AND %s
                GROUP BY name
                ORDER BY SUM(cases) DESC
            """, (start, end))
            rows = cur.fetchall()

    if not rows:
        await ctx.send("ไม่มีข้อมูลในสัปดาห์นี้")
        return

    msg = f"📆 **สรุปสัปดาห์ ({start} → {end})**\n"
    for name, cases in rows:
        msg += f"- {name}: {cases} เคส\n"

    await ctx.send(msg)

@bot.command()
@is_pbt()
async def resetdb(ctx):
    db_url = os.getenv("DATABASE_URL")

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        cur.execute("TRUNCATE TABLE cases RESTART IDENTITY;")
        conn.commit()

        cur.close()
        conn.close()

        await ctx.send("🧨 **ลบข้อมูลในฐานข้อมูลทั้งหมดเรียบร้อยแล้ว**")

    except Exception as e:
        await ctx.send("❌ Reset DB ไม่สำเร็จ")
        print(e)

bot.run(TOKEN)
