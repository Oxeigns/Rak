import logging
from telegram import Update
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus, ChatType

# Path check kar lena sahi hai ya nahi
from ai_moderation import ai_moderation_service

logger = logging.getLogger(__name__)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Analyze text/captions and delete unsafe content with Admin protection."""
    if not update.effective_chat or not update.effective_user:
        return

    # edited_message bhi handle karte hain
    message = update.message or update.edited_message
    user = update.effective_user
    if not message or user.is_bot:
        return

    content_to_analyze = message.text or message.caption
    if not content_to_analyze:
        return

    chat = update.effective_chat

    # 1. ADMIN PROTECTION: Admins/Owners ke messages check nahi karne chahiye
    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        try:
            member = await chat.get_member(user.id)
            if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                return # Admin hai toh chhod do
        except Exception as e:
            logger.debug(f"Could not verify admin status: {e}")

    # 2. AI Analysis with Timeout protection
    try:
        # analyze_message call
        ai_result = await ai_moderation_service.analyze_message(
            content_to_analyze,
            context={
                "chat_id": chat.id,
                "user_id": user.id,
            },
        )
    except Exception as e:
        logger.error(f"AI Service Failure: {e}")
        return

    # 3. Decision Logic
    is_safe = ai_result.get("is_safe", True)
    # Default scores 0.0 rakhte hain agar key na mile
    illegal_score = float(ai_result.get("illegal_score", 0.0))
    toxic_score = float(ai_result.get("toxicity_score", 0.0))
    spam_score = float(ai_result.get("spam_score", 0.0))

    # Thresholds (Inhe aap adjust kar sakte hain)
    should_delete = (
        is_safe is False or 
        illegal_score > 0.6 or 
        toxic_score > 0.7 or
        spam_score > 0.85
    )

    if not should_delete:
        return

    # 4. Bot Permission Check (Delete karne se pehle)
    try:
        bot_member = await chat.get_member(context.bot.id)
        if not bot_member.can_delete_messages:
            logger.warning(f"Bot lacks delete permissions in {chat.id}")
            return
    except Exception as e:
        logger.error(f"Permission check error: {e}")
        return

    # 5. Final Action: Delete and Warn
    try:
        await message.delete()
        
        user_mention = f"@{user.username}" if user.username else f"<b>{user.first_name}</b>"
        reason = ai_result.get("reason", "Unsafe content detected by AI")
        
        warn_text = (
            f"🚫 <b>Content Removed!</b>\n\n"
            f"Bhai {user_mention}, aapka message policy ke khilaaf tha.\n"
            f"<b>Vajah:</b> {reason}"
        )
        
        await context.bot.send_message(
            chat_id=chat.id,
            text=warn_text,
            parse_mode="HTML"
        )
        logger.info(f"Action: Deleted {message.message_id} | User: {user.id} | Reason: {reason}")

    except BadRequest as e:
        if "message to delete not found" in str(e).lower():
            pass
    except Forbidden:
        logger.error(f"Forbidden: Bot kicked or restricted in {chat.id}")
    except TelegramError as e:
        logger.error(f"Telegram API Error during deletion: {e}")
