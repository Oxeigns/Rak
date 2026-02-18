"""
AI Governor Bot - Control Panel System
Premium inline keyboard UI for admin management
"""

from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest
from telegram.ext import CallbackContext

from config.settings import get_settings
from utils.i18n import get_text


@dataclass
class MenuState:
    """Menu navigation state."""
    current_menu: str
    previous_menus: List[str]
    data: Dict


class ControlPanel:
    """
    Premium inline control panel with smooth navigation.
    All interactions use message editing instead of new messages.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.user_states: Dict[int, MenuState] = {}
        
    def _get_menu_keyboard(
        self, 
        menu_name: str, 
        group_id: int,
        language: str = "en"
    ) -> InlineKeyboardMarkup:
        """Generate keyboard for specific menu."""
        
        menus = {
            "main": self._main_menu_buttons,
            "protection": self._protection_menu_buttons,
            "engagement": self._engagement_menu_buttons,
            "trust_system": self._trust_menu_buttons,
            "raid_protection": self._raid_menu_buttons,
            "analytics": self._analytics_menu_buttons,
            "personality": self._personality_menu_buttons,
            "language": self._language_menu_buttons,
            "advanced_ai": self._advanced_ai_menu_buttons,
            "system_status": self._system_status_buttons,
        }
        
        builder = menus.get(menu_name, self._main_menu_buttons)
        return builder(group_id, language)
    
    def _main_menu_buttons(self, group_id: int, language: str) -> InlineKeyboardMarkup:
        """Main control panel menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{t('shield')} {t('protection_settings')}", 
                    callback_data=f"cp:protection:{group_id}"
                ),
                InlineKeyboardButton(
                    f"{t('fire')} {t('engagement_engine')}", 
                    callback_data=f"cp:engagement:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('trust')} {t('trust_system')}", 
                    callback_data=f"cp:trust_system:{group_id}"
                ),
                InlineKeyboardButton(
                    f"{t('shield_alert')} {t('raid_protection')}", 
                    callback_data=f"cp:raid_protection:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('chart')} {t('analytics')}", 
                    callback_data=f"cp:analytics:{group_id}"
                ),
                InlineKeyboardButton(
                    f"{t('sparkles')} {t('personality_mode')}", 
                    callback_data=f"cp:personality:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('globe')} {t('language')}", 
                    callback_data=f"cp:language:{group_id}"
                ),
                InlineKeyboardButton(
                    f"{t('brain')} {t('advanced_ai')}", 
                    callback_data=f"cp:advanced_ai:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('activity')} {t('system_status')}", 
                    callback_data=f"cp:system_status:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _protection_menu_buttons(
        self, 
        group_id: int, 
        language: str
    ) -> InlineKeyboardMarkup:
        """Protection settings menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{t('toggle_on')} Spam Shield", 
                    callback_data=f"cp_toggle:spam_shield:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('toggle_on')} AI Abuse Detection", 
                    callback_data=f"cp_toggle:ai_abuse:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('toggle_on')} Link Intelligence", 
                    callback_data=f"cp_toggle:link_intel:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('toggle_off')} Strict Mode", 
                    callback_data=f"cp_toggle:strict_mode:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('toggle_off')} Crypto Scam Shield", 
                    callback_data=f"cp_toggle:crypto_shield:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('toggle_off')} Deep Media Analysis", 
                    callback_data=f"cp_toggle:deep_media:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('back')} {t('back_to_main')}", 
                    callback_data=f"cp:main:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _engagement_menu_buttons(
        self, 
        group_id: int, 
        language: str
    ) -> InlineKeyboardMarkup:
        """Engagement engine menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{t('toggle_on')} Daily Question", 
                    callback_data=f"cp_toggle:daily_q:{group_id}"
                ),
                InlineKeyboardButton(
                    f"{t('toggle_off')} Weekly Poll", 
                    callback_data=f"cp_toggle:weekly_poll:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('toggle_off')} Member Spotlight", 
                    callback_data=f"cp_toggle:spotlight:{group_id}"
                ),
                InlineKeyboardButton(
                    f"{t('toggle_on')} Leaderboard", 
                    callback_data=f"cp_toggle:leaderboard:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('toggle_off')} Achievement Badges", 
                    callback_data=f"cp_toggle:badges:{group_id}"
                ),
                InlineKeyboardButton(
                    f"{t('toggle_on')} Inactive Reminders", 
                    callback_data=f"cp_toggle:inactive:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('back')} {t('back_to_main')}", 
                    callback_data=f"cp:main:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _trust_menu_buttons(self, group_id: int, language: str) -> InlineKeyboardMarkup:
        """Trust system menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{t('view')} View Trust Leaderboard", 
                    callback_data=f"cp_action:trust_leaderboard:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('edit')} Edit Trust Thresholds", 
                    callback_data=f"cp_action:trust_thresholds:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('reset')} Reset All Trust Scores", 
                    callback_data=f"cp_action:trust_reset:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('back')} {t('back_to_main')}", 
                    callback_data=f"cp:main:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _raid_menu_buttons(self, group_id: int, language: str) -> InlineKeyboardMarkup:
        """Raid protection menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{t('toggle_on')} Auto-Protect", 
                    callback_data=f"cp_toggle:raid_auto:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('edit')} Join Threshold (10)", 
                    callback_data=f"cp_action:raid_threshold:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('edit')} Time Window (30s)", 
                    callback_data=f"cp_action:raid_window:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('shield')} Emergency Lockdown", 
                    callback_data=f"cp_action:raid_lockdown:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('back')} {t('back_to_main')}", 
                    callback_data=f"cp:main:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _analytics_menu_buttons(
        self, 
        group_id: int, 
        language: str
    ) -> InlineKeyboardMarkup:
        """Analytics menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{t('chart')} Daily Report", 
                    callback_data=f"cp_action:analytics_daily:{group_id}"
                ),
                InlineKeyboardButton(
                    f"{t('chart')} Weekly Report", 
                    callback_data=f"cp_action:analytics_weekly:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('chart')} Monthly Report", 
                    callback_data=f"cp_action:analytics_monthly:{group_id}"
                ),
                InlineKeyboardButton(
                    f"{t('download')} Export Data", 
                    callback_data=f"cp_action:analytics_export:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('back')} {t('back_to_main')}", 
                    callback_data=f"cp:main:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _personality_menu_buttons(
        self, 
        group_id: int, 
        language: str
    ) -> InlineKeyboardMarkup:
        """Personality mode menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{t('selected')} Friendly", 
                    callback_data=f"cp_personality:friendly:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('select')} Strict", 
                    callback_data=f"cp_personality:strict:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('select')} Corporate", 
                    callback_data=f"cp_personality:corporate:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('select')} Funny", 
                    callback_data=f"cp_personality:funny:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('select')} Owner-Style", 
                    callback_data=f"cp_personality:owner:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('back')} {t('back_to_main')}", 
                    callback_data=f"cp:main:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _language_menu_buttons(
        self, 
        group_id: int, 
        language: str
    ) -> InlineKeyboardMarkup:
        """Language selection menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{'●' if language == 'en' else '○'} English", 
                    callback_data=f"cp_language:en:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{'●' if language == 'hi' else '○'} Hindi", 
                    callback_data=f"cp_language:hi:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{'●' if language == 'hinglish' else '○'} Hinglish", 
                    callback_data=f"cp_language:hinglish:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('back')} {t('back_to_main')}", 
                    callback_data=f"cp:main:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _advanced_ai_menu_buttons(
        self, 
        group_id: int, 
        language: str
    ) -> InlineKeyboardMarkup:
        """Advanced AI settings menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{t('edit')} AI Context Window", 
                    callback_data=f"cp_action:ai_context:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('edit')} Personality Strength", 
                    callback_data=f"cp_action:ai_strength:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('toggle_on')} Multi-language", 
                    callback_data=f"cp_toggle:ai_multilang:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('toggle_on')} Context Awareness", 
                    callback_data=f"cp_toggle:ai_context:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('back')} {t('back_to_main')}", 
                    callback_data=f"cp:main:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def _system_status_buttons(
        self, 
        group_id: int, 
        language: str
    ) -> InlineKeyboardMarkup:
        """System status menu."""
        t = lambda key: get_text(key, language)
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{t('refresh')} Refresh Status", 
                    callback_data=f"cp_action:status_refresh:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('view')} View Logs", 
                    callback_data=f"cp_action:view_logs:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('view')} API Usage", 
                    callback_data=f"cp_action:api_usage:{group_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{t('back')} {t('back_to_main')}", 
                    callback_data=f"cp:main:{group_id}"
                ),
            ],
        ]
        
        return InlineKeyboardMarkup(keyboard)
    
    def get_menu_text(self, menu_name: str, language: str = "en") -> str:
        """Get menu header text."""
        t = lambda key: get_text(key, language)
        
        headers = {
            "main": f"**{t('control_panel')}**\n\n{t('select_option')}",
            "protection": f"**{t('protection_settings')}**\n\n{t('toggle_features')}",
            "engagement": f"**{t('engagement_engine')}**\n\n{t('engage_members')}",
            "trust_system": f"**{t('trust_system')}**\n\n{t('manage_trust')}",
            "raid_protection": f"**{t('raid_protection')}**\n\n{t('raid_settings')}",
            "analytics": f"**{t('analytics')}**\n\n{t('view_stats')}",
            "personality": f"**{t('personality_mode')}**\n\n{t('select_tone')}",
            "language": f"**{t('language')}**\n\n{t('select_language')}",
            "advanced_ai": f"**{t('advanced_ai')}**\n\n{t('ai_settings')}",
            "system_status": f"**{t('system_status')}**\n\n{t('view_status')}",
        }
        
        return headers.get(menu_name, headers["main"])
    
    async def _is_admin_user(self, context: CallbackContext, group_id: int, user_id: int) -> bool:
        member = await context.bot.get_chat_member(group_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)

    async def show_menu(
        self,
        update: Update,
        context: CallbackContext,
        menu_name: str = "main",
        group_id: int = None,
        language: str = "en",
    ):
        """Show control panel menu by editing message."""
        query = update.callback_query

        if group_id is None:
            raise ValueError("group_id is required for control panel rendering")

        actor = update.effective_user
        if actor and not await self._is_admin_user(context, group_id, actor.id):
            if query:
                await query.answer(get_text("not_admin", language), show_alert=True)
            return

        keyboard = self._get_menu_keyboard(menu_name, group_id, language)
        text = self.get_menu_text(menu_name, language)

        try:
            if query:
                await query.edit_message_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            elif update.message:
                await update.message.reply_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        except BadRequest as exc:
            if "Message is not modified" in str(exc):
                if query:
                    await query.answer("No changes to display.")
                return
            raise


# Global control panel instance
control_panel = ControlPanel()
