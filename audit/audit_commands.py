# audit/audit_commands.py
from discord.ext import commands
from audit.audit_helpers import find_duplicate_person_in_message

def setup_audit_commands(bot, get_conn, is_pbt):

    @commands.command(name="audit")
    @is_pbt()
    async def audit_person(ctx, section: str = None):
        if section is None or section.lower() != "person":
            await ctx.send("ใช้ `!audit person`")
            return

        rows = find_duplicate_person_in_message(get_conn)

        if not rows:
            await ctx.send("✅ ไม่พบการแท็กซ้ำ")
            return

        msg = "🚨 **พบการแท็กชื่อซ้ำในข้อความเดียวกัน**\n\n"
        for message_id, name, count in rows:
            msg += f"- {name} | msg={message_id} | {count} ครั้ง\n"

        await ctx.send(msg)

    # ❗ สำคัญมาก: add หลังจากประกาศฟังก์ชันแล้ว
    bot.add_command(audit_person)
