import os
import sys
import logging
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, MessageHandler, filters

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

    # Build python-telegram-bot application
    app = ApplicationBuilder().token(bot_token).build()

    # Add text message handler (pure agentic loop dispatcher)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_telegram_message))

    logger.info("Kirana Store Ops Agent Bot is live and long-polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
