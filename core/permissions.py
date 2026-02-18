from __future__ import annotations

import logging

from telegram import Bot, ChatMemberAdministrator, ChatMemberOwner
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from core.config import AppConfig, ConfigError

logger = logging.getLogger(__name__)


class PermissionValidationError(RuntimeError):
    pass


async def validate_startup_permissions(bot: Bot, config: AppConfig) -> None:
    try:
        me = await bot.get_me()
    except RetryAfter as exc:
        raise PermissionValidationError(f'Telegram RetryAfter while fetching bot identity: {exc.retry_after}') from exc
    except (NetworkError, TelegramError) as exc:
        raise PermissionValidationError('Unable to fetch bot identity from Telegram API.') from exc

    if config.REQUIRE_FORCE_JOIN:
        await _validate_force_join_channel(bot, me.id, config)


async def _validate_force_join_channel(bot: Bot, bot_id: int, config: AppConfig) -> None:
    chat_id = config.FORCE_JOIN_CHANNEL_ID
    if chat_id >= 0:
        raise ConfigError('FORCE_JOIN_CHANNEL_ID must be negative for channels/supergroups.')

    try:
        chat = await bot.get_chat(chat_id)
    except BadRequest as exc:
        raise PermissionValidationError('FORCE_JOIN_CHANNEL_ID is invalid or inaccessible.') from exc
    except Forbidden as exc:
        raise PermissionValidationError('Bot has no access to force-join channel.') from exc
    except RetryAfter as exc:
        raise PermissionValidationError(f'Telegram retry-after while validating force-join channel: {exc.retry_after}') from exc
    except (NetworkError, TelegramError) as exc:
        raise PermissionValidationError('Telegram API error during force-join validation.') from exc

    if chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP):
        raise PermissionValidationError('FORCE_JOIN_CHANNEL_ID must reference a channel/supergroup.')

    try:
        me_member = await bot.get_chat_member(chat_id, bot_id)
    except RetryAfter as exc:
        raise PermissionValidationError(f'Telegram retry-after while reading bot permissions: {exc.retry_after}') from exc
    except (BadRequest, Forbidden, NetworkError, TelegramError) as exc:
        raise PermissionValidationError('Cannot inspect bot membership in force-join channel.') from exc

    if isinstance(me_member, ChatMemberOwner):
        logger.info('Bot is channel owner; all permission checks passed.', extra={'chat_id': chat_id, 'action': 'startup_validate'})
        return

    if not isinstance(me_member, ChatMemberAdministrator):
        raise PermissionValidationError('Bot must be administrator in force-join channel.')

    # Telegram permission fields can differ by chat type. Enforce only permissions
    # that are explicitly available and required for force-join operations.
    missing = []
    if me_member.can_invite_users is False:
        missing.append('can_invite_users')

    if chat.type == ChatType.SUPERGROUP and me_member.can_restrict_members is False:
        missing.append('can_restrict_members')

    if missing:
        raise PermissionValidationError(f'Bot admin lacks required force-join permissions: {", ".join(missing)}.')

    if chat.username and f'@{chat.username.lower()}' != config.FORCE_JOIN_CHANNEL.lower():
        raise PermissionValidationError('FORCE_JOIN_CHANNEL does not match username of FORCE_JOIN_CHANNEL_ID.')

    logger.info('Force-join startup validation completed.', extra={'chat_id': chat_id, 'action': 'startup_validate'})
