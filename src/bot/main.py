import os
import sys
import logging
from typing import Any
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, MessageHandler, filters
from telegram.request import HTTPXRequest

# Load environment variables
load_dotenv()

from src.db.init_db import init_db
from src.bot.handlers import handle_telegram_message

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main() -> None:
    """Main Telegram long-polling bot startup routine."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token or bot_token == "your_telegram_bot_token_here":
        logger.error("TELEGRAM_BOT_TOKEN is missing in environment variables. Exiting.")
        sys.exit(1)

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or gemini_key == "your_gemini_api_key_here":
        logger.warning("GEMINI_API_KEY is missing or unconfigured. Agent tool calls will fail until set.")

    # Initialize SQLite Database with WAL mode & DDL schema
    logger.info("Initializing SQLite database with WAL mode...")
    init_db()

    # Build python-telegram-bot application with custom timeouts to prevent bootstrap timeouts
    request = HTTPXRequest(connect_timeout=20.0, read_timeout=20.0)
    app = ApplicationBuilder().token(bot_token).request(request).build()

    # Add text/command message handler (pure agentic loop dispatcher)
    app.add_handler(MessageHandler(filters.ALL, handle_telegram_message))

    async def error_handler(update: object, context: Any) -> None:
        import telegram.error
        if isinstance(context.error, telegram.error.Conflict):
            logger.error("Conflict Error: Another instance of the bot is already running with this TELEGRAM_BOT_TOKEN. Terminate other bot processes first.")
        else:
            logger.error(f"Unhandled exception in bot loop: {context.error}", exc_info=context.error)

    app.add_error_handler(error_handler)

    logger.info("Kirana Store Ops Agent Bot is live and long-polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
