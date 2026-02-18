"""
AI Governor Bot - Main Application Entry Point
Production-ready FastAPI server with webhook/polling support
"""

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from telegram import Update
from telegram.ext import MessageHandler, filters

from config.settings import get_settings
from core.bot import governor_bot
from handlers.moderator import (
    moderate_animation,
    moderate_edited_photo,
    moderate_edited_text,
    moderate_photo,
    moderate_sticker,
    moderate_text,
    moderate_video,
)
from models.database import db_manager
from services.ai_service import moderation_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()


def register_message_handler() -> None:
    """Register moderation handlers in telegram application."""
    governor_bot.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, moderate_text))
    governor_bot.application.add_handler(MessageHandler(filters.PHOTO, moderate_photo))
    governor_bot.application.add_handler(MessageHandler(filters.Sticker.ALL, moderate_sticker))
    governor_bot.application.add_handler(MessageHandler(filters.ANIMATION, moderate_animation))
    governor_bot.application.add_handler(MessageHandler(filters.VIDEO, moderate_video))
    governor_bot.application.add_handler(MessageHandler(filters.TEXT & filters.UpdateType.EDITED_MESSAGE, moderate_edited_text))
    governor_bot.application.add_handler(MessageHandler(filters.PHOTO & filters.UpdateType.EDITED_MESSAGE, moderate_edited_photo))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    app.state.polling_task = None

    try:
        logger.info("Starting AI Governor Bot...")

        await db_manager.initialize()
        await db_manager.create_tables()
        logger.info("Database initialized")

        await moderation_service.initialize()
        logger.info("AI service initialized")

        await governor_bot.initialize()
        await governor_bot.application.initialize()
        register_message_handler()

        if settings.WEBHOOK_URL:
            await governor_bot.application.bot.set_webhook(
                url=settings.WEBHOOK_URL,
                secret_token=settings.WEBHOOK_SECRET or None,
                allowed_updates=Update.ALL_TYPES,
            )
            logger.info("Webhook mode enabled at %s", settings.WEBHOOK_URL)
        else:
            await governor_bot.application.start()
            app.state.polling_task = asyncio.create_task(
                governor_bot.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            )
            logger.info("Bot started in polling mode")

        yield

    except Exception:
        logger.exception("Fatal error during startup")
        raise
    finally:
        logger.info("Shutting down AI Governor Bot...")

        try:
            if governor_bot.application:
                if settings.WEBHOOK_URL:
                    await governor_bot.application.bot.delete_webhook(drop_pending_updates=False)
                else:
                    if app.state.polling_task:
                        await governor_bot.application.updater.stop()
                        app.state.polling_task.cancel()
                        with suppress(asyncio.CancelledError):
                            await app.state.polling_task

                if governor_bot.application.running:
                    await governor_bot.application.stop()
                await governor_bot.application.shutdown()
        except Exception:
            logger.exception("Error while stopping Telegram application")

        await moderation_service.cleanup()
        await db_manager.close()
        logger.info("Shutdown complete")


app = FastAPI(
    title="AI Governor Bot",
    description="Revolutionary AI-Powered Telegram Group Management",
    version=settings.BOT_VERSION,
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {"status": "operational", "bot": settings.BOT_NAME, "version": settings.BOT_VERSION}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": asyncio.get_event_loop().time(),
    }


@app.post("/webhook")
async def webhook(request: Request):
    """Telegram webhook endpoint with secret verification and safe update parsing."""
    if not settings.WEBHOOK_URL:
        raise HTTPException(status_code=404, detail="Webhook mode is disabled")

    if settings.WEBHOOK_SECRET:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not hmac.compare_digest(header_secret or "", settings.WEBHOOK_SECRET):
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    try:
        update = Update.de_json(payload, governor_bot.application.bot)
    except Exception as exc:
        logger.exception("Failed to parse webhook update")
        raise HTTPException(status_code=400, detail="Invalid update payload") from exc

    await governor_bot.application.process_update(update)
    return Response(status_code=200)


@app.get("/api/stats")
async def get_stats():
    return {
        "groups_managed": 0,
        "messages_processed": 0,
        "violations_detected": 0,
        "users_protected": 0,
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=1, reload=False)
