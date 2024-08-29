import logging
import os
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from telegram import Update, Chat, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Load environment variables from .env file
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    logger.error("MONGO_URI is not set in the environment variables.")
    raise ValueError("MONGO_URI is not set in the environment variables.")

client = AsyncIOMotorClient(MONGO_URI)
db = client.telegram_bot
collection = db.collected_data
user_collection = db.users  # Collection to store private chat user IDs
notification_collection = db.notifications  # Collection to track notifications

async def start(update: Update, _: CallbackContext) -> None:
    user = update.message.from_user
    chat_type = update.message.chat.type

    # Collect user information
    username = user.username
    first_name = user.first_name
    last_name = user.last_name
    user_id = user.id

    if chat_type == Chat.PRIVATE:
        # Check if the user is already in the database
        user_data = await user_collection.find_one({"user_id": user_id})
        if user_data is None:
            trial_end_date = (datetime.utcnow() + timedelta(days=3)).strftime('%Y-%m-%d')

            await user_collection.insert_one({
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "user_id": user_id,
                "status": True,  # Set status to True for active
                "trial_end_date": trial_end_date
            })
            logger.info(f"Added user {user_id} to the database with status 'True'.")
            await update.message.reply_text("Hello! I'm a bot that collects text from groups. You have a 3-day free trial.")
        else:
            logger.info(f"User {user_id} already registered.")
            await update.message.reply_text("You have already started. I'm here to collect text from groups.")

# Function to collect data from the group
async def collect_data(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    chat = update.message.chat
    chat_name = chat.title if chat.title else chat.username or "Private Chat"
    text = update.message.text if update.message.text else update.message.caption

    if not text:
        return

    text_lower = text.lower()
    keywords = [
        "for rent", "rental", "rent", "available for rent", "leasing", "rental property", "for lease", "rental unit",
        "ქირავდება", "გასაცემი", "გასაქირავებელი", "დაქირავება", "ქირა", "ხელმისაწვდომი",
        "аренда", "сдается", "арендуется", "арендовать", "на аренду", "Сниму"
    ]

    if not any(keyword in text_lower for keyword in keywords):
        return

    if chat.username:
        message_link = f"https://t.me/{chat.username}/{update.message.message_id}"
    else:
        message_link = f"https://t.me/{chat_name}/{update.message.message_id}"

    user_link = f"https://t.me/{user.username}" if user.username else None

    collected_data = {
        'user_link': user_link,
        'text': text,
        'message_link': message_link,
        'chat_name': chat_name,
        'message_id': update.message.message_id
    }

    try:
        await collection.insert_one(collected_data)
        logger.info("Data inserted successfully.")
        await notify_users(context, collected_data)
    except Exception as e:
        logger.error(f"Error saving data to MongoDB: {e}")

# Function to notify users about new data
async def notify_users(context: CallbackContext, data: dict) -> None:
    summary = f"{data.get('text', 'No text')}"
    buttons = []
    if data.get('user_link'):
        buttons.append(InlineKeyboardButton(text="User Link", url=data['user_link']))
    if data.get('message_link'):
        buttons.append(InlineKeyboardButton(text="Message Link", url=data['message_link']))
    reply_markup = InlineKeyboardMarkup([[*buttons]])

    async for user in user_collection.find({"status": True}):  # Only notify active users
        user_id = user["user_id"]
        trial_end_date_str = user.get("trial_end_date")
        if trial_end_date_str:
            trial_end_date = datetime.strptime(trial_end_date_str, '%Y-%m-%d')
            if datetime.utcnow() >= trial_end_date:
                await user_collection.update_one({"user_id": user_id}, {"$set": {"status": False}})  # Update to False when trial ends
                logger.info(f"User {user_id} trial period ended. Status changed to 'False'.")
                continue

        if await notification_collection.find_one({"user_id": user_id, "message_id": data['message_id']}):
            continue

        try:
            await context.bot.send_message(chat_id=user_id, text=summary, reply_markup=reply_markup)
            logger.info(f"Notification sent to user {user_id}.")
            await notification_collection.insert_one({"user_id": user_id, "message_id": data['message_id']})
        except Exception as e:
            logger.error(f"Error sending notification to user {user_id}: {e}")

# Error handler
async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f"Update {update} caused error {context.error}")

def main() -> None:
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN is not set in the environment variables.")
        raise ValueError("BOT_TOKEN is not set in the environment variables.")

    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.ALL, collect_data))
    
    commands = [BotCommand("start", "Start the bot")]
    application.bot.set_my_commands(commands)
    
    application.add_error_handler(error)
    application.run_polling()

if __name__ == '__main__':
    main()
