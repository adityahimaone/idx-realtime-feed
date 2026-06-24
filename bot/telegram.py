"""
Telegram formatter + sender.
Direct HTTP via httpx (works as standalone cron job).
"""
import os
import sys
import asyncio
import httpx

# Allow imports from app root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Telegram config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # e.g. -1001234567890 or @channelname


async def send_telegram(message: str, parse_mode: str = "MarkdownV2") -> bool:
    """
    Send message to Telegram. Returns True on success.
    parse_mode: "MarkdownV2" or "HTML"
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            # Fallback: retry without parse_mode on formatting errors (400)
            if resp.status_code == 400 and parse_mode:
                payload_plain = {**payload, "parse_mode": None}
                del payload_plain["parse_mode"]
                resp2 = await client.post(url, json=payload_plain)
                if resp2.status_code == 200:
                    return True
                print(f"Telegram send failed (plain fallback): {resp2.status_code} {resp2.text}", file=sys.stderr)
                return False
            print(f"Telegram send failed: {resp.status_code} {resp.text}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"Telegram send error: {e}", file=sys.stderr)
        return False


def escape_md(text: str) -> str:
    """
    Escape special characters for Telegram MarkdownV2.
    """
    special = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special:
        text = text.replace(char, f'\\{char}')
    return text
