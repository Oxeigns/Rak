"""
AI Governor Bot - Main Bot Handler
Core message processing and event handling
"""

import logging
import asyncio
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from settings import get_settings
from database import Group, GroupSettings, GroupType, GroupUser, Message, RiskLevel, User, db_manager
from ai_services import ai_moderation_service
from anti_raid import anti_raid_system
from control_panel import control_panel
from risk_engine import risk_engine
from trust_engine import trust_engine
from helpers import (
    auto_delete_message,
    get_all_groups,
    get_all_users,
    is_user_joined,
    ensure_user_joined,
    verify_join_callback,
)
from i18n import get_text

# Import handlers
from handlers.commands import CommandHandlers
from handlers.callbacks import CallbackHandlers
from handlers.messages import MessageHandlers

logger = logging.getLogger(__name__)


class AIGovernorBot(CommandHandlers, CallbackHandlers, MessageHandlers):
    """AI Governor Bot - Telegram event orchestration."""

    def __init__(self):
        self.settings = get_settings()
        self.application: Optional[Application] = None
        self._handlers_registered = False
        self._promotion_tasks = []
        self._button_clicks: dict[int, deque[float]] = defaultdict(deque)

    async def initialize(self):
        """Initialize telegram application and register all handlers before start."""
        if self.application is not None:
            return

        self.application = Application.builder().token(self.settings.BOT_TOKEN).build()
        self._register_handlers()
        self._promotion_tasks.append(asyncio.create_task(self._group_promotion_loop()))
        self._promotion_tasks.append(asyncio.create_task(self._dm_promotion_loop()))

    def _register_handlers(self):
        """Register all bot handlers exactly once."""
        if self._handlers_registered:
            return

        app = self.application
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("panel", self.cmd_panel))
        app.add_handler(CommandHandler("pannel", self.cmd_panel))
        app.add_handler(CommandHandler("guide", self.cmd_guide))
        app.add_handler(CommandHandler("set_edit", self.cmd_set_edit_autodelete))

        # 1. Most specific handlers FIRST (settings with specific sub-actions)
        app.add_handler(CallbackQueryHandler(self.handle_set_autodelete, pattern=r"^cp_action:set_autodelete:"))
        app.add_handler(CallbackQueryHandler(self.handle_set_edited_autodelete, pattern=r"^cp_action:set_edited_autodelete:"))
        app.add_handler(CallbackQueryHandler(self.handle_set_threshold, pattern=r"^cp_action:set_threshold:"))
        app.add_handler(CallbackQueryHandler(self.handle_set_mute_duration, pattern=r"^cp_action:set_mute_duration:"))
        app.add_handler(CallbackQueryHandler(self.handle_set_max_warnings, pattern=r"^cp_action:set_max_warnings:"))
        
        # 2. Then other pattern handlers (more specific to less specific)
        app.add_handler(CallbackQueryHandler(self.handle_toggle, pattern=r"^cp_toggle:"))
        app.add_handler(CallbackQueryHandler(self.handle_action, pattern=r"^cp_action:"))
        app.add_handler(CallbackQueryHandler(self.handle_language, pattern=r"^cp_language:"))
        app.add_handler(CallbackQueryHandler(self.handle_personality, pattern=r"^cp_personality:"))
        
        # 3. Generic handler LAST (catches remaining cp: patterns)
        app.add_handler(CallbackQueryHandler(self.handle_callback, pattern=r"^cp:"))
        app.add_handler(CallbackQueryHandler(verify_join_callback, pattern=r"^verify_join$"))

        app.add_handler(ChatMemberHandler(self.handle_chat_member, ChatMemberHandler.ANY_CHAT_MEMBER))
        app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.handle_new_members))
        # Admin text input handler
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            self.handle_text_input,
            block=False
        ))
        app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, self.handle_message))

        app.add_error_handler(self.handle_error)
        self._handlers_registered = True

    # Helper methods
    async def _is_admin(self, chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            return member.status in {"administrator", "creator"}
        except TelegramError:
            return False

    async def _get_group(self, group_id: int) -> Optional[Group]:
        async with db_manager.get_session() as session:
            result = await session.execute(select(Group).where(Group.id == group_id))
            return result.scalar_one_or_none()

    async def _get_group_language(self, group_id: int) -> str:
        group = await self._get_group(group_id)
        return group.language if group else "en"

    async def _create_group(self, chat):
        async with db_manager.get_session() as session:
            existing = (await session.execute(select(Group).where(Group.id == chat.id))).scalar_one_or_none()
            if existing:
                return

            group_type = GroupType.SUPERGROUP if chat.type == "supergroup" else GroupType.PUBLIC
            session.add(
                Group(
                    id=chat.id,
                    title=chat.title or "Unknown",
                    username=chat.username,
                    group_type=group_type,
                )
            )
            await session.commit()

    async def _ensure_user_exists(self, telegram_user) -> None:
        async with db_manager.get_session() as session:
            await session.execute(
                insert(User)
                .values(
                    id=telegram_user.id,
                    username=telegram_user.username,
                    first_name=telegram_user.first_name,
                    last_name=telegram_user.last_name,
                    language_code=telegram_user.language_code or "en",
                    is_bot=telegram_user.is_bot,
                )
                .on_conflict_do_nothing(index_elements=[User.id])
            )
            await session.commit()

    async def _log_message(self, message, risk_assessment, group_id, telegram_user):
        async with db_manager.get_session() as session:
            async with session.begin():
                await self._ensure_user_exists(telegram_user)
                session.add(
                    Message(
                        message_id=message.message_id,
                        group_id=group_id,
                        user_id=telegram_user.id,
                        text=message.text,
                        risk_score=risk_assessment.final_score,
                        risk_level=RiskLevel.coerce(risk_assessment.risk_level),
                        action_taken=risk_assessment.action,
                    )
                )

    async def _handle_violation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, risk_assessment):
        chat = update.effective_chat
        user = update.effective_user
        message = update.effective_message

        if not chat or not user or not message:
            return

        violation_text = (
            f"⚠️ <b>Content Violation Detected</b>\n\n"
            f"User: {user.mention_html()}\n"
            f"Risk Score: {risk_assessment.final_score}/100\n"
            f"Action: {risk_assessment.action}"
        )

        if risk_assessment.reason:
            violation_text += f"\nReason: {risk_assessment.reason}"

        await context.bot.send_message(
            chat_id=chat.id,
            text=violation_text,
            parse_mode="HTML",
        )

        db_risk_level = RiskLevel.coerce(risk_assessment.risk_level)

        trust_update = await trust_engine.calculate_trust_update(
            user.id,
            chat.id,
            "violation",
            severity=db_risk_level.normalized,
        )

        async with db_manager.get_session() as session:
            await trust_engine.update_user_trust(user.id, chat.id, trust_update.new_score, session)

    async def _handle_warning(self, update: Update, context: ContextTypes.DEFAULT_TYPE, risk_assessment):
        chat = update.effective_chat
        user = update.effective_user
        message = update.effective_message

        if not chat or not user or not message:
            return

        warning_text = f"⚠️ {user.mention_html()}, your message may violate group rules."

        warn_msg = await context.bot.send_message(
            chat_id=chat.id,
            text=warning_text,
            parse_mode="HTML",
            reply_to_message_id=message.message_id,
        )

        db_risk_level = RiskLevel.coerce(risk_assessment.risk_level)

        trust_update = await trust_engine.calculate_trust_update(
            user.id,
            chat.id,
            "violation",
            severity=db_risk_level.normalized,
        )

        async with db_manager.get_session() as session:
            await trust_engine.update_user_trust(user.id, chat.id, trust_update.new_score, session)

    async def _send_welcome_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return

        text = (
            f"{self.settings.BOT_NAME} Activated\n\n"
            "Protection System Activated:\n"
            "✓ Spam Shield\n"
            "✓ AI Abuse Detection\n"
            "✓ Link Intelligence\n"
            "✓ Anti-Raid System\n"
            "✓ Trust Score Engine\n"
            "✓ Media Scanner\n\n"
            "Use /panel to customize settings."
        )

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Open Control Panel", callback_data=f"cp:main:{chat.id}")]]
        )

        await context.bot.send_message(chat_id=chat.id, text=text, reply_markup=keyboard)

    def _parse_callback_payload(self, data: str, prefix: str) -> Optional[Tuple[str, int]]:
        """Parse callback data like 'cp_toggle:strict_mode:12345'."""
        if not data.startswith(f"{prefix}:"):
            return None
        parts = data.split(":")
        if len(parts) != 3:
            return None
        try:
            return parts[1], int(parts[2])
        except ValueError:
            return None

    async def _rate_limited(self, user_id: int) -> bool:
        """Check if user is rate limited."""
        now = time.time()
        user_clicks = self._button_clicks[user_id]
        while user_clicks and user_clicks[0] < now - self.settings.BUTTON_CLICK_RATE_LIMIT_WINDOW_SECONDS:
            user_clicks.popleft()
        if len(user_clicks) >= self.settings.BUTTON_CLICK_RATE_LIMIT_MAX:
            return True
        user_clicks.append(now)
        return False

    async def _handle_raid_detection(self, update, context, raid_result):
        chat = update.effective_chat
        if not chat:
            return

        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "🚨 RAID DETECTED 🚨\n\n"
                f"Type: {raid_result.raid_type}\n"
                f"Confidence: {raid_result.confidence:.0%}\n\n"
                "Protection activated."
            ),
        )

    async def _group_promotion_loop(self):
        while True:
            await asyncio.sleep(max(1, self.settings.GROUP_PROMOTION_INTERVAL) * 3600)
            await self._send_group_promotion()

    async def _dm_promotion_loop(self):
        while True:
            await asyncio.sleep(max(1, self.settings.DM_PROMOTION_INTERVAL) * 3600)
            await self._send_dm_promotion()

    async def _send_group_promotion(self):
        if not self.application:
            return
        try:
            groups = await get_all_groups()
            promo_text = """◆ 🤖 ʀᴀᴋsʜᴀᴋ ᴀɪ ɢᴜᴀʀᴅɪᴀɴ 💗

━━━━━━━━━━━━━━━━━━━━━━━━━━

ᴋᴇᴇᴘɪɴɢ ʏᴏᴜʀ ɢʀᴏᴜᴘ sᴀғᴇ ᴀɴᴅ ᴄʟᴇᴀɴ

⚘ ғᴇᴀᴛᴜʀᴇs :-

● ᴀɪ ᴄᴏɴᴛᴇɴᴛ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ
● sᴛɪᴄᴋᴇʀ & ɢɪғ ᴀɴᴀʟʏsɪs
● ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ sʏsᴛᴇᴍ

━━━━━━━━━━━━━━━━━━━━━━━━━━

• ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ •"""
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("• ᴀᴅᴅ ᴍᴇ ʙᴀʙʏ •", url=f"https://t.me/{self.application.bot.username}?startgroup=true")]]
            )
            for group_id in groups:
                try:
                    msg = await self.application.bot.send_message(chat_id=group_id, text=promo_text, reply_markup=keyboard)
                    asyncio.create_task(auto_delete_message(msg, 3600))
                except Exception:
                    continue
        except Exception as exc:
            logger.error("Group promotion error: %s", exc)

    async def _send_dm_promotion(self):
        if not self.application:
            return
        try:
            users = await get_all_users()
            promo_text = """◆ ʜᴇʏ ᴛʜᴇʀᴇ 👋 💗

━━━━━━━━━━━━━━━━━━━━━━━━━━

ᴍɪss ᴍᴇ ? ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ
ᴀɴᴅ ᴋᴇᴇᴘ ɪᴛ sᴀғᴇ ғʀᴏᴍ sᴘᴀᴍ & ᴛᴏxɪᴄɪᴛʏ

━━━━━━━━━━━━━━━━━━━━━━━━━━

• ᴀᴅᴅ ᴍᴇ ɴᴏᴡ •"""
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("• ᴀᴅᴅ ᴍᴇ ʙᴀʙʏ •", url=f"https://t.me/{self.application.bot.username}?startgroup=true")]]
            )
            for user_id in users:
                try:
                    await self.application.bot.send_message(chat_id=user_id, text=promo_text, reply_markup=keyboard)
                except Exception:
                    continue
        except Exception as exc:
            logger.error("DM promotion error: %s", exc)

    async def _get_total_groups(self) -> int:
        return len(await get_all_groups())

    async def _get_total_violations(self) -> int:
        async with db_manager.get_session() as session:
            rows = await session.execute(select(GroupUser.violation_count))
            return int(sum(row[0] or 0 for row in rows.all()))


governor_bot = AIGovernorBot()


async def run_bot() -> None:
    """Run the bot with database initialization and graceful shutdown."""
    await db_manager.initialize()
    await db_manager.create_tables()

    await governor_bot.initialize()
    app = governor_bot.application
    if app is None:
        raise RuntimeError("Telegram application failed to initialize")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(run_bot())
