# audit/audit_commands.py
from discord.ext import commands
from .case_audit import CaseAudit


def setup_audit_commands(bot, get_conn, is_pbt):
    audit = CaseAudit(get_conn)

    @bot.command()
    @is_pbt()
    async def audit(ctx, section: str = None):
        if section is None:
            await ctx.send(
                "🧪 **Audit Commands**\n\n"
                "`!audit dup` — ตรวจ message ซ้ำ\n"
                "`!audit person` — ตรวจคนซ้ำใน message เดียว\n"
                "`!audit old` — ตรวจเคสเก่า (เสี่ยง edit ข้ามวัน)"
            )
            return

        if section == "dup":
            rows = audit.find_duplicate_messages()
            if not rows:
                await ctx.send("✅ ไม่พบ message ซ้ำ")
                return

            msg = "⚠️ **พบ message_id ซ้ำ**\n"
            for mid, count in rows:
                msg += f"- message_id `{mid}` : {count} records\n"
            await ctx.send(msg)

        elif section == "person":
            rows = audit.find_duplicate_person_in_message()
            if not rows:
                await ctx.send("✅ ไม่พบคนซ้ำใน message เดียว")
                return

            msg = "⚠️ **พบคนซ้ำใน message เดียว**\n"
            for mid, name, count in rows:
                msg += f"- {name} | message `{mid}` : {count}\n"
            await ctx.send(msg)

        elif section == "old":
            rows = audit.find_old_cases()
            if not rows:
                await ctx.send("✅ ไม่มีเคสเก่า")
                return

            msg = "⚠️ **เคสเก่า (เสี่ยงโดนแก้ย้อนหลัง)**\n"
            for _, name, date, mid in rows[:10]:
                msg += f"- {name} | {date} | `{mid}`\n"
            await ctx.send(msg)

        else:
            await ctx.send("❌ ไม่รู้จัก audit section")
