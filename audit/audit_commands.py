from discord.ext import commands
from audit.audit_helpers import find_duplicate_person_in_message
from audit.audit_export import export_audit_csv, export_audit_xlsx
from datetime import datetime
import discord
import os


def setup_audit_commands(bot, get_conn, is_pbt):

    @commands.command(name="audit")
    @is_pbt()
    async def audit(
        ctx,
        subcmd: str = None,
        export_type: str = None,
        start: str = None,
        end: str = None
    ):

        # =====================
        # audit person
        # =====================
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

        # =====================
        # audit export
        # =====================
        if subcmd == "export":

            # ถ้า user ไม่ใส่ csv / excel → default = both
            if export_type not in ("csv", "excel"):
                start_str = export_type
                export_type = "both"
            else:
                start_str = start

            # กันกรณีไม่ใส่วันที่
            if not start_str:
                await ctx.send(
                    "❌ ใช้:\n"
                    "`!audit export csv DD/MM/YYYY [DD/MM/YYYY]`\n"
                    "`!audit export excel DD/MM/YYYY [DD/MM/YYYY]`\n"
                    "`!audit export DD/MM/YYYY [DD/MM/YYYY]`"
                )
                return

            try:
                start_date = datetime.strptime(start_str, "%d/%m/%Y").date()
                end_date = (
                    datetime.strptime(end, "%d/%m/%Y").date()
                    if end else start_date
                )
            except Exception:
                await ctx.send(
                    "❌ รูปแบบวันที่ไม่ถูกต้อง\n"
                    "ใช้ `DD/MM/YYYY` เช่น `17/12/2025`"
                )
                return

            files = []
            count = None

            # ===== CSV =====
            if export_type in ("csv", "both"):
                csv_file, count = export_audit_csv(
                    get_conn, start_date, end_date
                )

                if count == 0:
                    await ctx.send("📭 ไม่มี audit log ในช่วงวันที่นี้")
                    return

                files.append(
                    discord.File(
                        fp=csv_file,
                        filename=f"audit_{start_date}_{end_date}.csv"
                    )
                )

            # ===== Excel =====
            if export_type in ("excel", "both"):
                xlsx_path, excel_count = export_audit_xlsx(
                    get_conn, start_date, end_date
                )

                # ถ้ายังไม่มี count (กรณี export excel อย่างเดียว)
                if count is None:
                    count = excel_count

                if count == 0:
                    await ctx.send("📭 ไม่มี audit log ในช่วงวันที่นี้")
                    return

                files.append(
                    discord.File(
                        fp=xlsx_path,
                        filename=f"audit_{start_date}_{end_date}.xlsx"
                    )
                )

            await ctx.send(
                content=(
                    f"🧾 Audit log {count} รายการ\n"
                    f"📅 ช่วงวันที่ {start_date} → {end_date}"
                ),
                files=files
            )

            # ===== cleanup temp files (xlsx only) =====
            for f in files:
                try:
                    if f.filename.endswith(".xlsx"):
                        os.remove(f.fp)
                except Exception as e:
                    print("⚠️ temp file cleanup failed:", e)

            return

        # =====================
        # help
        # =====================
        await ctx.send(
            "📖 **Audit Commands**\n\n"
            "- `!audit person`\n"
            "- `!audit export csv DD/MM/YYYY [DD/MM/YYYY]`\n"
            "- `!audit export excel DD/MM/YYYY [DD/MM/YYYY]`\n"
            "- `!audit export DD/MM/YYYY [DD/MM/YYYY]` (ส่งทั้ง CSV + Excel)"
        )

    # register command
    bot.add_command(audit)
