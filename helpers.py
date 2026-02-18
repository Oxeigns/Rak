import logging
from functools import wraps
from typing import Awaitable, Callable, TypeVar

from config.settings import get_settings

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

settings = get_settings()

FORCE_JOIN_CHANNEL_ID = settings.FORCE_JOIN_CHANNEL_ID
FORCE_JOIN_CHANNEL_LINK = settings.FORCE_JOIN_CHANNEL_LINK
FORCE_JOIN_DENIED_MESSAGE = (
    "⚠️ <b>Access Denied!</b>\n\nBhai, Rakshak Bot ko use karne ke liye aapko hamare official channel ko join karna hoga. Join karne ke baad niche 'Done' button pe click karein."
)
VERIFY_CALLBACK_DATA = "verify_join"

_ALLOWED_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
}

HandlerFunc = TypeVar("HandlerFunc", bound=Callable[..., Awaitable[None]])

def _force_join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Join Official Channel", url=FORCE_JOIN_CHANNEL_LINK)],
            [InlineKeyboardButton("✅ Done / Verify", callback_data=VERIFY_CALLBACK_DATA)],
        ]
    )

async def _is_joined(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False

    # Skip check if not configured
    if not FORCE_JOIN_CHANNEL_ID or FORCE_JOIN_CHANNEL_ID == 0:
        return True

    try:
        member = await context.bot.get_chat_member(FORCE_JOIN_CHANNEL_ID, user.id)
        return member.status in _ALLOWED_STATUSES
    except (Forbidden, BadRequest) as exc:
        # User has never started the bot or bot is not admin in the channel
        logger.warning(f"Force-join check failed for {user.id}: {exc}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in force-join check: {e}")
        return False

async def send_force_join_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the force join message with keyboard."""
    params = {
        "text": FORCE_JOIN_DENIED_MESSAGE,
        "reply_markup": _force_join_keyboard(),
        "parse_mode": "HTML"
    }
    
    if update.callback_query:
        await update.callback_query.message.reply_text(**params)
    elif update.message:
        await update.message.reply_text(**params)

async def ensure_user_joined(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Global helper to check membership."""
    if await _is_joined(update, context):
        return True

    await send_force_join_prompt(update, context)
    return False

def is_user_joined(func: HandlerFunc) -> HandlerFunc:
    """Decorator for private chats and commands.

    Supports both free handlers (update, context) and bound class methods
    (self, update, context).
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        if len(args) < 2:
            return await func(*args, **kwargs)

        if isinstance(args[0], Update):
            update = args[0]
            context = args[1]
            call_args = args
        else:
            if len(args) < 3:
                return await func(*args, **kwargs)
            update = args[1]
            context = args[2]
            call_args = args

        if not isinstance(update, Update):
            return await func(*args, **kwargs)

        if not update.effective_chat or not update.effective_user:
            return await func(*call_args, **kwargs)

        # Force join logic only for Private chats OR Commands in groups
        is_private = update.effective_chat.type == ChatType.PRIVATE
        is_command = bool(update.message and update.message.text and update.message.text.startswith("/"))

        if is_private or is_command:
            if await _is_joined(update, context):
                return await func(*call_args, **kwargs)
            
            await send_force_join_prompt(update, context)
            return None
            
        return await func(*call_args, **kwargs)

    return wrapper

async def verify_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Done / Verify' button click."""
    query = update.callback_query
    if not query:
        return

    if await _is_joined(update, context):
        # FIX: Success alert and delete the prompt message to clean chat
        await query.answer("✅ Verification successful! Ab aap bot use kar sakte ho.", show_alert=True)
        try:
            await query.message.delete()
        except:
            pass
    else:
        # FIX: Show alert instead of sending more messages
        await query.answer("❌ Abhi join detect nahi hua. Pehle channel join karo aur phir 'Done' dabao.", show_alert=True)
