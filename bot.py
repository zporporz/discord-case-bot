import csv
from datetime import datetime
import os
import discord
from discord.ext import commands
from datetime import timedelta
import re
import psycopg2

def save_case_pg(name, channel, cases, message_id):
    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        print("❌ DATABASE_URL not found")
        return

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO cases (date, name, channel, cases, message_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (message_id) DO NOTHING
        """, (
            datetime.now().strftime("%Y-%m-%d"),
            name,
            channel,
            cases,
            str(message_id)
        ))

        conn.commit()
        cur.close()
        conn.close()

        print(f"✅ Saved to DB: {name} +{cases}")

    except Exception as e:
        print("❌ DB error:", e)


def normalize_name(name: str):
    # ตัด +xxx, [GRPL], emoji คร่าว ๆ
    name = re.sub(r"\+?\d+\s*", "", name)
    name = re.sub(r"\[.*?\]\s*", "", name)
    return name.strip().lower()


def is_sun_to_sat(start_date, end_date):
    # Sunday = 6, Saturday = 5 (ตาม weekday ของ Python)
    return (
        start_date.weekday() == 6
        and end_date.weekday() == 5
        and (end_date - start_date).days == 6
    )

def get_week_range_sun_sat():
    today = datetime.now()
    weekday = today.weekday()  # Mon=0 ... Sun=6

    # ถอยกลับไปวันอาทิตย์ล่าสุด
    days_since_sunday = (weekday + 1) % 7
    start = today - timedelta(days=days_since_sunday)

    # วันเสาร์
    end = start + timedelta(days=6)

    return (
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d")
    )

def import_csv_once():
    # ถ้าเซ็ตแล้ว แปลว่าเคย import ไปแล้ว
    if os.getenv("CSV_IMPORTED") == "1":
        print("🔒 CSV system disabled (CSV_IMPORTED=1)")
        return

    csv_path = "cases.csv"
    if not os.path.exists(csv_path):
        print("ℹ️ cases.csv not found, skip import")
        return

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL not found")
        return

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    count = 0
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur.execute("""
                INSERT INTO cases (date, name, channel, cases, message_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING
            """, (
                row["date"],
                row["name"],
                row["channel"],
                int(row["cases"]),
                row["message_id"]
            ))
            count += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ CSV imported into PostgreSQL: {count} rows")


TOKEN = os.getenv("DISCORD_TOKEN")

PBT_ROLE_ID = 1393537553264545922  # <-- ใส่ Role ID ผบตร.
RESET_PASSWORD = "GRPL2025"
pending_reset = {}

CASE10_CHANNEL_ID = 1443212808316780654  # ใส่ ID ห้องเคสจุด10
NORMAL_CHANNEL_IDS = [
    1393542799617691658,
    1400477664900288576 # ใส่ ID ห้องคดีปกติ
]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    partials=["message", "channel"]
)

PROCESSED_FILE = "processed_messages.txt"

def remove_case_by_message_id(message_id):
    if not os.path.exists("cases.csv"):
        return

    rows = []
    with open("cases.csv", "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("message_id") != str(message_id):
                rows.append(row)

    with open("cases.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "name", "channel", "case_type", "cases", "message_id"]
        )
        writer.writeheader()
        writer.writerows(rows)

def save_case(name, channel, case_type, cases, message_id):
    file_exists = os.path.exists("cases.csv")

    with open("cases.csv", "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(["date", "name", "channel", "case_type", "cases", "message_id"])

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d"),
            name,
            channel,
            case_type,   # 👈 เพิ่ม
            cases,
            str(message_id)
        ])


def load_processed():
    if not os.path.exists(PROCESSED_FILE):
        return set()
    with open(PROCESSED_FILE, "r") as f:
        return set(line.strip() for line in f.readlines())
        
DELETED_FILE = "deleted_messages.txt"

def load_deleted():
    if not os.path.exists(DELETED_FILE):
        return set()
    with open(DELETED_FILE, "r") as f:
        return set(line.strip() for line in f.readlines())

def save_deleted(message_id):
    with open(DELETED_FILE, "a") as f:
        f.write(f"{message_id}\n")

deleted_messages = load_deleted()

@bot.event
async def on_message_delete(message):
    if not message or not message.id or not message.channel:
        return

    # เช็กเฉพาะห้องเคสเท่านั้น
    valid_channels = [CASE10_CHANNEL_ID] + NORMAL_CHANNEL_IDS

    if message.channel.id not in valid_channels:
        return  # ไม่ใช่ห้องเคส → ไม่สนใจ

    deleted_messages.add(str(message.id))
    save_deleted(message.id)

    print(f"❌ ลบเคสจากห้อง {message.channel.name} | message_id = {message.id}")

@bot.event
async def on_message_edit(before, after):
    if after.author.bot:
        return

    if not after.channel or not after.id:
        return

    valid_channels = [CASE10_CHANNEL_ID] + NORMAL_CHANNEL_IDS
    if after.channel.id not in valid_channels:
        return

    # ลบเคสเดิม
    remove_case_by_message_id(after.id)

    mentions = after.mentions
    if not mentions:
        print(f"✏️ แก้ข้อความ แต่ไม่มี mention → message_id {after.id}")
        return

    if after.channel.id == CASE10_CHANNEL_ID:
        case_value = 2
        case_type = "case10"
    else:
        case_value = 1
        case_type = "normal"

    for member in mentions:
        save_case(
            member.display_name,
            after.channel.name,
            case_type,
            case_value,
            after.id
        )


    print(f"✏️ แก้ไขเคสใหม่จาก message_id = {after.id}")
      

def save_processed(message_id):
    with open(PROCESSED_FILE, "a") as f:
        f.write(f"{message_id}\n")

processed_messages = load_processed()

@bot.event
async def on_ready():
    print(f"บอทออนไลน์แล้ว: {bot.user}")

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    
    if message.author.bot:
        return
    if str(message.id) in processed_messages:
        return

    mentions = message.mentions
    if not mentions:
        return

    if message.channel.id == CASE10_CHANNEL_ID:
        case_value = 2
        case_type = "case10"
    elif message.channel.id in NORMAL_CHANNEL_IDS:
        case_value = 1
        case_type = "normal"
    else:
        return


    for member in mentions:
    print(f"{member.display_name} +{case_value} เคส")

    # ✅ STEP 2: เขียนลง PostgreSQL
    save_case_pg(
        member.display_name,
        message.channel.name,
        case_value,
        message.id
    )

    # (ยังเก็บ CSV ไว้ก่อน)
    save_case(
        member.display_name,
        message.channel.name,
        case_type,
        case_value,
        message.id
    )

    processed_messages.add(str(message.id))
    save_processed(message.id)
    
@bot.command(name="cmd")
async def cmd(ctx, section: str = None):

    # ======================
    # CMD ทั่วไป (ทุกคน)
    # ======================
    if section is None:
        msg = (
            "📖 **คำสั่งบอทนับเคส**\n\n"
            "👮 **คำสั่งทั่วไป**\n"
            "`!today` — ดูสรุปเคสวันนี้\n"
            "`!me` — ดูเคสของตัวเองวันนี้\n"
            "`!date 12/12` — ดูเคสตามวันที่\n"
            "`!week` — สรุปเคสประจำสัปดาห์\n\n"
            "ℹ️ พิมพ์ `!cmd admin` สำหรับคำสั่งผู้บังคับบัญชา"
        )
        await ctx.send(msg)
        return

    # ======================
    # CMD สถิติ
    # ======================
    if section.lower() == "stats":
        msg = (
            "📊 **คำสั่งสถิติ**\n"
            "`!today` — สรุปเคสวันนี้\n"
            "`!week` — อาทิตย์–เสาร์\n"
            "`!date DD/MM` — ดูย้อนหลัง"
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
            "🛑 **คำสั่งผู้บังคับบัญชา (ผบตร.)**\n"
            "`!reset all` — ล้างข้อมูลทั้งหมด\n"
            "`!reset processed` — ล้างประวัติกันซ้ำ\n"
            "`!reset deleted` — ล้างประวัติลบเคส\n"
            "`!confirm <password>` — ยืนยันการ reset"
        )
        await ctx.send(msg)
        return

    # ======================
    # CMD ไม่รู้จัก
    # ======================
    await ctx.send("❓ ไม่พบหมวดคำสั่งนี้ ใช้ `!cmd` หรือ `!cmd admin`")
   
@bot.command()
async def today(ctx):
    today_str = datetime.now().strftime("%Y-%m-%d")

    summary = {
        "normal": {},
        "case10": {}
    }

    if not os.path.exists("cases.csv"):
        await ctx.send("ยังไม่มีข้อมูลเคส")
        return

    with open("cases.csv", "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:

            if row.get("message_id") in deleted_messages:
                continue

            if row["date"] != today_str:
                continue

            name = row["name"]
            case_type = row.get("case_type", "normal")
            cases = int(row["cases"])

            if case_type not in summary:
                continue

            if name not in summary[case_type]:
                summary[case_type][name] = {
                    "cases": 0,
                    "incidents": 0
                }

            summary[case_type][name]["cases"] += cases
            summary[case_type][name]["incidents"] += 1

    if not summary["normal"] and not summary["case10"]:
        await ctx.send("วันนี้ยังไม่มีเคส")
        return

    msg = "📊 **สรุปคดีวันนี้**\n\n"

    if summary["normal"]:
        msg += "🟦 **คดีปกติ**\n"
        for name in sorted(summary["normal"], key=normalize_name):
            data = summary["normal"][name]
            msg += f"- {name}: {data['incidents']} คดี ({data['cases']} เคส)\n"
        msg += "\n"

    if summary["case10"]:
        msg += "🟥 **คดีจุด 10**\n"
        for name in sorted(summary["case10"], key=normalize_name):
            data = summary["case10"][name]
            msg += f"- {name}: {data['incidents']} คดี ({data['cases']} เคส)\n"

    await ctx.send(msg)



@bot.command()
async def me(ctx):
    today = datetime.now().strftime("%Y-%m-%d")
    my_name = ctx.author.display_name

    incidents = 0   # จำนวนคดี
    cases_total = 0 # จำนวนเคส

    if not os.path.exists("cases.csv"):
        await ctx.send("ยังไม่มีข้อมูลเคส")
        return

    with open("cases.csv", "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (
                row["date"] == today
                and row["name"] == my_name
                and row.get("message_id") not in deleted_messages
            ):
                incidents += 1
                cases_total += int(row["cases"])

    if incidents == 0:
        await ctx.send(f"👮 {my_name}\nวันนี้ยังไม่มีคดี")
        return

    await ctx.send(
        f"👮 {my_name}\n"
        f"วันนี้ทำ {incidents} คดี ({cases_total} เคส)"
    )


@bot.command()
async def date(ctx, date_str: str):
    try:
        if len(date_str.split("/")) == 2:
            day, month = date_str.split("/")
            year = datetime.now().year
        else:
            day, month, year = date_str.split("/")

        target_date = datetime(
            int(year), int(month), int(day)
        ).strftime("%Y-%m-%d")
    except:
        await ctx.send("❌ รูปแบบวันที่ไม่ถูกต้อง ใช้แบบ 12/12 หรือ 12/12/2025")
        return

    summary = {}

    if not os.path.exists("cases.csv"):
        await ctx.send("ยังไม่มีข้อมูลเคส")
        return

    with open("cases.csv", "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (
                row["date"] == target_date
                and row.get("message_id") not in deleted_messages
            ):
                name = row["name"]
                cases = int(row["cases"])

                if name not in summary:
                    summary[name] = {
                        "cases": 0,
                        "incidents": 0
                    }

                summary[name]["cases"] += cases
                summary[name]["incidents"] += 1

    if not summary:
        await ctx.send(f"📅 วันที่ {date_str} ไม่มีคดี")
        return

    msg = f"📊 **สรุปคดีวันที่ {date_str}**\n"
    for name in sorted(summary, key=normalize_name):
        data = summary[name]
        msg += f"- {name}: {data['incidents']} คดี ({data['cases']} เคส)\n"

    await ctx.send(msg)

    
def is_pbt():
    async def predicate(ctx):
        return any(role.id == PBT_ROLE_ID for role in ctx.author.roles)
    return commands.check(predicate)


@bot.command()
@is_pbt()
async def reset(ctx, mode: str = "all"):
    if mode not in ["all", "processed", "deleted"]:
        await ctx.send("❌ ใช้คำสั่ง: `!reset all | processed | deleted`")
        return

    pending_reset[ctx.author.id] = mode

    await ctx.send(
        f"⚠️ คุณกำลังจะ reset `{mode}`\n"
        f"พิมพ์ `!confirm <password>` เพื่อยืนยัน"
    )

 
@bot.command()
@is_pbt()
async def confirm(ctx, password: str):
    global processed_messages, deleted_messages

    if ctx.author.id not in pending_reset:
        await ctx.send("❌ ไม่มีรายการ reset ที่รอการยืนยัน")
        return

    if password != RESET_PASSWORD:
        await ctx.send("❌ รหัสผ่านไม่ถูกต้อง")
        return

    mode = pending_reset.pop(ctx.author.id)

    # ล้าง processed
    if mode in ["all", "processed"]:
        if os.path.exists(PROCESSED_FILE):
            os.remove(PROCESSED_FILE)
        processed_messages = set()

    # ล้าง deleted
    if mode in ["all", "deleted"]:
        if os.path.exists(DELETED_FILE):
            os.remove(DELETED_FILE)
        deleted_messages = set()

    # ล้างทั้งหมด
    if mode == "all":
        if os.path.exists("cases.csv"):
            os.remove("cases.csv")

        with open("cases.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "name", "channel", "cases", "message_id"])

    await ctx.send(f"✅ Reset `{mode}` สำเร็จแล้ว (ผบตร.)")
    
@reset.error
async def reset_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("⛔ คำสั่งนี้ใช้ได้เฉพาะ **ผบตร.** เท่านั้น")
    else:
        raise error
 
@confirm.error
async def confirm_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("⛔ คำสั่งนี้ใช้ได้เฉพาะ **ผบตร.** เท่านั้น")
    else:
        raise error

@bot.command()
async def week(ctx, start: str = None, end: str = None):
    if not os.path.exists("cases.csv"):
        await ctx.send("ยังไม่มีข้อมูลเคส")
        return

    # ====== กำหนดช่วงสัปดาห์ ======
    if start is None and end is None:
        start_date_str, end_date_str = get_week_range_sun_sat()
    elif start and end:
        try:
            d1, m1 = map(int, start.split("/"))
            d2, m2 = map(int, end.split("/"))
            year = datetime.now().year

            start_dt = datetime(year, m1, d1)
            end_dt = datetime(year, m2, d2)

            if not is_sun_to_sat(start_dt, end_dt):
                await ctx.send("❌ ต้องเป็นช่วง **อาทิตย์–เสาร์** เท่านั้น")
                return

            start_date_str = start_dt.strftime("%Y-%m-%d")
            end_date_str = end_dt.strftime("%Y-%m-%d")

        except:
            await ctx.send("❌ ใช้รูปแบบ `!week DD/MM DD/MM`")
            return
    else:
        await ctx.send("❌ ใช้ `!week` หรือ `!week DD/MM DD/MM`")
        return

    start_d = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_d = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    # ====== รวมข้อมูล ======
    summary = {}

    with open("cases.csv", "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:

            if row.get("message_id") in deleted_messages:
                continue

            try:
                row_date = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
            except:
                continue

            if start_d <= row_date <= end_d:
                name = row["name"]
                cases = int(row["cases"])

                if name not in summary:
                    summary[name] = {
                        "cases": 0,
                        "incidents": 0
                    }

                summary[name]["cases"] += cases
                summary[name]["incidents"] += 1

    if not summary:
        await ctx.send("ไม่มีข้อมูลในช่วงนี้")
        return

    # ====== แบ่งกลุ่มตามเคส ======
    group_500, group_400, group_300 = [], [], []

    for name, data in summary.items():
        total = data["cases"]
        if total >= 500:
            group_500.append((name, total))
        elif total >= 400:
            group_400.append((name, total))
        elif total >= 300:
            group_300.append((name, total))

    # ====== แสดงผล ======
    msg = (
        "📆 **สรุปเคสประจำสัปดาห์**\n"
        f"(อาทิตย์–เสาร์ {start_date_str} → {end_date_str})\n\n"
    )

    def add_group(title, data):
        nonlocal msg
        if data:
            msg += f"**{title}**\n"
            for name, total in sorted(data, key=lambda x: x[1], reverse=True):
                msg += f"- {name}: {total} เคส\n"
            msg += "\n"

    add_group("🔥 500+ เคส", group_500)
    add_group("💪 400+ เคส", group_400)
    add_group("✅ 300+ เคส", group_300)

    msg += "**📋 รวมทุกนาย (ทั้งหมดในช่วงนี้)**\n"
    for name in sorted(summary, key=normalize_name):
        msg += f"- {name}: {summary[name]['cases']} เคส\n"

    await ctx.send(msg)

import_csv_once()
bot.run(TOKEN)
