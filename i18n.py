"""
AI Governor Bot - Internationalization
Multi-language support for UI and messages
"""

from typing import Dict, Optional

# Translation dictionary
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # General
        "bot_name": "AI Governor",
        "welcome": "Welcome",
        "error": "An error occurred",
        "success": "Success",
        "cancel": "Cancel",
        "back": "←",
        "save": "Save",
        "delete": "Delete",
        "edit": "✎",
        "view": "👁",
        "refresh": "↻",
        "download": "⬇",
        "reset": "↺",
        "select": "○",
        "selected": "●",
        "toggle_on": "✓",
        "toggle_off": "✗",
        
        # Icons
        "shield": "🛡",
        "shield_alert": "🚨",
        "fire": "🔥",
        "trust": "✓",
        "chart": "📊",
        "sparkles": "✨",
        "globe": "🌐",
        "brain": "🧠",
        "activity": "📈",
        
        # Control Panel
        "control_panel": "Control Panel",
        "select_option": "Select an option to configure:",
        "protection_settings": "Protection",
        "engagement_engine": "Engagement",
        "trust_system": "Trust System",
        "raid_protection": "Raid Protection",
        "analytics": "Analytics",
        "personality_mode": "Personality",
        "language": "Language",
        "advanced_ai": "Advanced AI",
        "system_status": "System Status",
        "back_to_main": "Back",
        
        # Sub-menus
        "toggle_features": "Toggle protection features:",
        "engage_members": "Configure engagement features:",
        "manage_trust": "Manage trust scores:",
        "raid_settings": "Configure raid protection:",
        "view_stats": "View group statistics:",
        "select_tone": "Select bot personality:",
        "select_language": "Select language:",
        "ai_settings": "Configure AI settings:",
        "view_status": "View system status:",
        
        # Onboarding
        "activate_admin": "To activate full AI protection, please promote me to admin with these permissions:\n\n• Delete messages\n• Restrict users\n• Invite users\n• Pin messages",
        "select_language_prompt": "AI Governor activated.\n\nSelect language:",
        "protection_activated": "Protection System Activated:",
        "optional_upgrades": "Optional Upgrades Available:",
        "open_control_panel": "Open Control Panel",
        
        # Protections
        "spam_shield": "Spam Shield",
        "ai_abuse": "AI Abuse Detection",
        "link_intel": "Link Intelligence",
        "strict_mode": "Strict Mode",
        "crypto_shield": "Crypto Scam Shield",
        "deep_media": "Deep Media Analysis",
        
        # Actions
        "action_blocked": "Message blocked",
        "action_warned": "Warning issued",
        "action_muted": "User muted",
        "action_banned": "User banned",
        "action_deleted": "Message deleted",
        
        # Errors
        "not_admin": "◆ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ 🚫\n\nʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀɴ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪs ɢʀᴏᴜᴘ.",
        "permission_denied": "Permission denied.",
        "group_not_found": "Group not found in database.",
        "violation_removed": "◆ ᴄᴏɴᴛᴇɴᴛ ʀᴇᴍᴏᴠᴇᴅ 🚫",
        "admin_panel_title": "◆ ᴀᴅᴍɪɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ ⚙️",
    },
    
    "hi": {
        # Hindi translations
        "bot_name": "AI गवर्नर",
        "welcome": "स्वागत है",
        "error": "एक त्रुटि हुई",
        "success": "सफल",
        "cancel": "रद्द करें",
        "back": "←",
        "save": "सहेजें",
        "delete": "हटाएं",
        "edit": "✎",
        "view": "👁",
        "refresh": "↻",
        "download": "⬇",
        "reset": "↺",
        "select": "○",
        "selected": "●",
        "toggle_on": "✓",
        "toggle_off": "✗",
        
        "shield": "🛡",
        "shield_alert": "🚨",
        "fire": "🔥",
        "trust": "✓",
        "chart": "📊",
        "sparkles": "✨",
        "globe": "🌐",
        "brain": "🧠",
        "activity": "📈",
        
        "control_panel": "नियंत्रण पैनल",
        "select_option": "एक विकल्प चुनें:",
        "protection_settings": "सुरक्षा",
        "engagement_engine": "सहभागिता",
        "trust_system": "ट्रस्ट सिस्टम",
        "raid_protection": "रेड सुरक्षा",
        "analytics": "एनालिटिक्स",
        "personality_mode": "व्यक्तित्व",
        "language": "भाषा",
        "advanced_ai": "एडवांस AI",
        "system_status": "सिस्टम स्थिति",
        "back_to_main": "वापस",
        
        "toggle_features": "सुरक्षा सुविधाएं टॉगल करें:",
        "engage_members": "सहभागिता सुविधाएं कॉन्फ़िगर करें:",
        "manage_trust": "ट्रस्ट स्कोर प्रबंधित करें:",
        "raid_settings": "रेड सुरक्षा कॉन्फ़िगर करें:",
        "view_stats": "समूह आँकड़े देखें:",
        "select_tone": "बॉट व्यक्तित्व चुनें:",
        "select_language": "भाषा चुनें:",
        "ai_settings": "AI सेटिंग्स कॉन्फ़िगर करें:",
        "view_status": "सिस्टम स्थिति देखें:",
        
        "activate_admin": "पूर्ण AI सुरक्षा सक्रिय करने के लिए, कृपया मुझे इन अनुमतियों के साथ एडमिन बनाएं:\n\n• संदेश हटाएं\n• उपयोगकर्ताओं को प्रतिबंधित करें\n• उपयोगकर्ताओं को आमंत्रित करें\n• संदेश पिन करें",
        "select_language_prompt": "AI गवर्नर सक्रिय।\n\nभाषा चुनें:",
        "protection_activated": "सुरक्षा प्रणाली सक्रिय:",
        "optional_upgrades": "उपलब्ध वैकल्पिक अपग्रेड:",
        "open_control_panel": "नियंत्रण पैनल खोलें",
        
        "spam_shield": "स्पैम शील्ड",
        "ai_abuse": "AI दुर्व्यवहार पहचान",
        "link_intel": "लिंक इंटेलिजेंस",
        "strict_mode": "सख्त मोड",
        "crypto_shield": "क्रिप्टो घोटाला शील्ड",
        "deep_media": "डीप मीडिया विश्लेषण",
        
        "action_blocked": "संदेश अवरुद्ध",
        "action_warned": "चेतावनी जारी",
        "action_muted": "उपयोगकर्ता म्यूट",
        "action_banned": "उपयोगकर्ता प्रतिबंधित",
        "action_deleted": "संदेश हटाया गया",
        
        "not_admin": "◆ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ 🚫\n\nआप इस ग्रुप में एडमिन नहीं हैं।",
        "permission_denied": "अनुमति अस्वीकृत।",
        "group_not_found": "समूह डेटाबेस में नहीं मिला।",
        "violation_removed": "◆ ᴄᴏɴᴛᴇɴᴛ ʀᴇᴍᴏᴠᴇᴅ 🚫",
        "admin_panel_title": "◆ ᴀᴅᴍɪɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ ⚙️",
    },
    
    "hinglish": {
        # Hinglish (Hindi in Roman script)
        "bot_name": "AI Governor",
        "welcome": "Swagat hai",
        "error": "Koi error aaya",
        "success": "Ho gaya",
        "cancel": "Cancel",
        "back": "←",
        "save": "Save",
        "delete": "Delete",
        "edit": "✎",
        "view": "👁",
        "refresh": "↻",
        "download": "⬇",
        "reset": "↺",
        "select": "○",
        "selected": "●",
        "toggle_on": "✓",
        "toggle_off": "✗",
        
        "control_panel": "Control Panel",
        "select_option": "Koi option select karo:",
        "protection_settings": "Protection",
        "engagement_engine": "Engagement",
        "trust_system": "Trust System",
        "raid_protection": "Raid Protection",
        "analytics": "Analytics",
        "personality_mode": "Personality",
        "language": "Language",
        "advanced_ai": "Advanced AI",
        "system_status": "System Status",
        "back_to_main": "Back",
        
        "activate_admin": "Full AI protection chalu karne ke liye, mujhe admin banao with permissions:\n\n• Delete messages\n• Restrict users\n• Invite users\n• Pin messages",
        "select_language_prompt": "AI Governor chalu ho gaya.\n\nLanguage select karo:",
        "protection_activated": "Protection System Active:",
        "optional_upgrades": "Available Upgrades:",
        "open_control_panel": "Control Panel Kholo",
        
        "spam_shield": "Spam Shield",
        "ai_abuse": "AI Abuse Detection",
        "link_intel": "Link Intelligence",
        "strict_mode": "Strict Mode",
        "crypto_shield": "Crypto Scam Shield",
        "deep_media": "Deep Media Analysis",
        
        "action_blocked": "Message block ho gaya",
        "action_warned": "Warning diya gaya",
        "action_muted": "User mute ho gaya",
        "action_banned": "User ban ho gaya",
        "action_deleted": "Message delete ho gaya",
        
        "not_admin": "◆ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ 🚫\n\nTum admin nahi ho is group mein.",
        "permission_denied": "Permission nahi hai.",
        "group_not_found": "Group database mein nahi mila.",
        "violation_removed": "◆ ᴄᴏɴᴛᴇɴᴛ ʀᴇᴍᴏᴠᴇᴅ 🚫",
        "admin_panel_title": "◆ ᴀᴅᴍɪɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ ⚙️",
    }
}


def get_text(key: str, language: str = "en") -> str:
    """Get translated text for key."""
    lang_dict = TRANSLATIONS.get(language, TRANSLATIONS["en"])
    return lang_dict.get(key, TRANSLATIONS["en"].get(key, key))


def get_available_languages() -> list:
    """Get list of available languages."""
    return list(TRANSLATIONS.keys())


def detect_language(text: str) -> str:
    """Detect language of text."""
    try:
        from langdetect import detect
        detected = detect(text)
        if detected in TRANSLATIONS:
            return detected
        if detected == "hi":
            return "hi"
    except Exception:
        pass
    return "en"
