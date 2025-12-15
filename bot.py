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
from datetime import datetime

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
    print(f"🤖 Bot online: {bot.user}")


@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author.bot or not message.mentions:
        return

    # เลือกประเภทเคส
    if message.channel.id == CASE10_CHANNEL_ID:
        case_type = "case10"
        case_value = 2
    elif message.channel.id in NORMAL_CHANNEL_IDS:
        case_type = "normal"
        case_value = 1
    else:
        return

    message_date = message.created_at.astimezone().date()

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

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM cases WHERE message_id = %s",
                    (str(message.id),)
                )
        print(f"🗑️ Deleted cases | msg={message.id}")
    except Exception as e:
        print("❌ DB delete error:", e)


@bot.event
async def on_message_edit(before, after):
    if after.author.bot:
        return

    # กันแก้ไขข้ามวัน
    if after.created_at.date() != datetime.now().date():
        print(f"⛔ Ignore edit (old message) | msg={after.id}")
        return

    print(f"✏️ Message edited | msg={after.id}")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM cases WHERE message_id = %s",
                    (str(after.id),)
                )
        print(f"🗑️ Deleted old cases | msg={after.id}")
    except Exception as e:
        print("❌ DB delete error (edit):", e)
        return

    if not after.mentions:
        print(f"ℹ️ No mentions after edit | msg={after.id}")
        return

    if after.channel.id == CASE10_CHANNEL_ID:
        case_type = "case10"
        case_value = 2
    elif after.channel.id in NORMAL_CHANNEL_IDS:
        case_type = "normal"
        case_value = 1
    else:
        return

    message_date = after.created_at.astimezone().date()
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


# ======================
# COMMANDS
# ======================

@bot.command()
async def today(ctx):
    today = datetime.now().date()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(r"""
                SELECT name, case_type, COUNT(*), SUM(cases)
                FROM cases
                WHERE date = %s
                GROUP BY name, case_type
                ORDER BY regexp_replace(
                    name,
                    '^\+?\d+\s*\[.*?\]\s*',
                    '',
                    'g'
                )
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
    total_cases_all = 0

    for name, ctype, inc, total in rows:
        if name not in summary:
            summary[name] = {
                "normal_cases": 0,
                "normal_posts": 0,
                "point10_cases": 0,
                "point10_posts": 0
            }

        if ctype == "normal":
            summary[name]["normal_cases"] += total
            summary[name]["normal_posts"] += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc

        total_cases_all += total

    for name, data in summary.items():
        value = ""
        if data["normal_cases"] > 0:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"] > 0:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)"

        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    embed.set_footer(text=(
        f"📊 รวมทั้งหมด: {total_cases_all} เคส\n"
        f"🔒 ระบบป้องกันการนับซ้ำอัตโนมัติ"
    ))

    await ctx.send(embed=embed)

@bot.command()
async def me(ctx):
    today = datetime.now().date()
    name = ctx.author.display_name

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT case_type, COUNT(*), COALESCE(SUM(cases),0)
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

    total_cases_all = 0

    for ctype, inc, total in rows:
        label = "📂 คดีปกติ" if ctype == "normal" else "🚨 คดีจุด 10"
        embed.add_field(
            name=label,
            value=f"{total} เคส ({inc} คดี)",
            inline=False
        )
        total_cases_all += total

    embed.set_footer(text=(
        f"📊 รวมทั้งหมด: {total_cases_all} เคส\n"
        f"🔒 ระบบป้องกันการนับซ้ำอัตโนมัติ"
    ))

    await ctx.send(embed=embed)

@bot.command()
async def date(ctx, date_str: str):
    try:
        d, m = map(int, date_str.split("/"))
        y = datetime.now().year
        target = datetime(y, m, d).date()
    except:
        await ctx.send("❌ ใช้ `!date DD/MM`")
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(r"""
                SELECT name, case_type, COUNT(*), SUM(cases)
                FROM cases
                WHERE date = %s
                GROUP BY name, case_type
                ORDER BY regexp_replace(
                    name,
                    '^\+?\d+\s*\[.*?\]\s*',
                    '',
                    'g'
                )
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
    total_cases_all = 0

    for name, ctype, inc, total in rows:
        if name not in summary:
            summary[name] = {
                "normal_cases": 0,
                "normal_posts": 0,
                "point10_cases": 0,
                "point10_posts": 0
            }

        if ctype == "normal":
            summary[name]["normal_cases"] += total
            summary[name]["normal_posts"] += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc

        total_cases_all += total

    for name, data in summary.items():
        value = ""
        if data["normal_cases"] > 0:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"] > 0:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)"

        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    embed.set_footer(text=(
        f"📊 รวมทั้งหมด: {total_cases_all} เคส\n"
        f"🔒 ระบบป้องกันการนับซ้ำอัตโนมัติ"
    ))

    await ctx.send(embed=embed)

@bot.command()
async def week(ctx):
    start, end = get_week_range_sun_sat()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(r"""
                SELECT name, case_type, COUNT(*), SUM(cases)
                FROM cases
                WHERE date BETWEEN %s AND %s
                GROUP BY name, case_type
                ORDER BY regexp_replace(
                    name,
                    '^\+?\d+\s*\[.*?\]\s*',
                    '',
                    'g'
                )
            """, (start, end))
            rows = cur.fetchall()

    if not rows:
        await ctx.send(
            embed=Embed(
                description="📭 ไม่มีข้อมูลในสัปดาห์นี้",
                color=0x2f3136
            )
        )
        return

    embed = Embed(
        title="📊 Case Summary — Week",
        description=f"📆 ช่วงเวลา: {start.strftime('%d/%m')} → {end.strftime('%d/%m')}",
        color=0x2ecc71
    )

    summary = {}
    total_cases_all = 0

    for name, ctype, inc, total in rows:
        if name not in summary:
            summary[name] = {
                "normal_cases": 0,
                "normal_posts": 0,
                "point10_cases": 0,
                "point10_posts": 0
            }

        if ctype == "normal":
            summary[name]["normal_posts"] += inc
            summary[name]["normal_cases"] += total
        else:
            summary[name]["point10_posts"] += inc
            summary[name]["point10_cases"] += total

        total_cases_all += total

    for name, data in summary.items():
        value = ""
        if data["normal_cases"] > 0:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"] > 0:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)"

        embed.add_field(
            name=f"👤 {name}",
            value=value,
            inline=False
        )

    embed.set_footer(
        text=(
            f"📊 รวมทั้งหมด: {total_cases_all} เคส\n"
            f"🔒 ระบบป้องกันการนับซ้ำอัตโนมัติ"
        )
    )

    await ctx.send(embed=embed)

@bot.command()
async def check(ctx, *, keyword: str = None):
    if not keyword:
        await ctx.send("❌ ใช้ `!check ชื่อ`")
        return

    today = datetime.now().date()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT name, case_type, COUNT(*), SUM(cases)
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

    summary = {}
    total_cases_all = 0

    for name, ctype, inc, total in rows:
        if name not in summary:
            summary[name] = {
                "normal_cases": 0,
                "normal_posts": 0,
                "point10_cases": 0,
                "point10_posts": 0
            }

        if ctype == "normal":
            summary[name]["normal_cases"] += total
            summary[name]["normal_posts"] += inc
        else:
            summary[name]["point10_cases"] += total
            summary[name]["point10_posts"] += inc

        total_cases_all += total

    for name, data in summary.items():
        value = ""
        if data["normal_cases"] > 0:
            value += f"📂 คดีปกติ: {data['normal_cases']} เคส ({data['normal_posts']} คดี)\n"
        if data["point10_cases"] > 0:
            value += f"🚨 คดีจุด 10: {data['point10_cases']} เคส ({data['point10_posts']} คดี)"

        embed.add_field(name=f"👤 {name}", value=value, inline=False)

    embed.set_footer(text=f"📊 รวมทั้งหมด: {total_cases_all} เคส")

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
            "`!date DD/MM` — ดูคดีย้อนหลังตามวันที่\n"
            "`!week` — สรุปคดีประจำสัปดาห์ (อาทิตย์–เสาร์)\n"
            "`!check ชื่อ` — 🔍 เช็กคดีของบุคคล (วันนี้)"
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
