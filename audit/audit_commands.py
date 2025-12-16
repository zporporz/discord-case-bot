from discord.ext import commands
from audit.audit_helpers import find_duplicate_person_in_message
from audit.audit_export import export_audit_csv
from datetime import datetime
import discord


def setup_audit_commands(bot, get_conn, is_pbt):

    @commands.command(name="audit")
    @is_pbt()
    async def audit(ctx, subcmd: str = None, start: str = None, end: str = None):

        # ===== audit person =====
        if subcmd == "person":
            rows = find_duplicate_person_in_message(get_conn)

            if not rows:
                await ctx.send("✅ ไม่พบการแท็กซ้ำ")
                return

            msg = "🚨 **พบการแท็กชื่อซ้ำในข้อความเดียวกัน**\n\n"
            for message_id, name, count in rows:
                msg += f"- {name} | msg={message_id} | {count} ครั้ง\n"

            await ctx.send(msg)
            return

        # ===== audit export =====
        if subcmd == "export":
            try:
                start_date = datetime.strptime(start, "%d/%m/%Y").date()
                end_date = (
                    datetime.strptime(end, "%d/%m/%Y").date()
                    if end else start_date
                )
            except Exception:
                await ctx.send("❌ ใช้ `!audit export DD/MM/YYYY [DD/MM/YYYY]`")
                return

            file_obj, count = export_audit_csv(get_conn, start_date, end_date)

            if count == 0:
                await ctx.send("📭 ไม่มี audit log ในช่วงวันที่นี้")
                return

            file = discord.File(
                fp=file_obj,
                filename=f"audit_{start_date}_{end_date}.csv"
            )

            await ctx.send(
                content=f"🧾 Audit log {count} รายการ ({start_date} → {end_date})",
                file=file
            )
            return

        # ===== help =====
        await ctx.send(
            "ใช้คำสั่ง:\n"
            "- `!audit person`\n"
            "- `!audit export DD/MM/YYYY [DD/MM/YYYY]`"
        )

    # 🔥 add แค่ครั้งเดียว
    bot.add_command(audit)
