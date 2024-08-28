import logging
import os
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

# Define the start command
async def start(update: Update, _: CallbackContext) -> None:
    user_id = update.message.from_user.id
    chat_type = update.message.chat.type

    if chat_type == Chat.PRIVATE:
        # Add user ID to the database if not already present
        if await user_collection.find_one({"user_id": user_id}) is None:
            await user_collection.insert_one({"user_id": user_id})
            logger.info(f"Added user {user_id} to the database.")
    
    await update.message.reply_text("Hello! I'm a bot that collects text from groups.")

# Function to collect data from the group
async def collect_data(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user  # Get the user who sent the message
    chat = update.message.chat  # Get the chat where the message was sent
    chat_name = chat.title if chat.title else chat.username or "Private Chat"

    # Collect the message text or caption
    text = update.message.text if update.message.text else update.message.caption

    # If both text and caption are None, return early
    if not text:
        return

    # Convert text to lowercase for keyword matching
    text_lower = text.lower()

    # List of keywords to check for
    keywords = [
        "for rent", "rental", "rent", "available for rent", "leasing", "rental property", "for lease", "rental unit",
        "ქირავდება", "გასაცემი", "გასაქირავებელი", "დაქირავება", "ქირა", "ხელმისაწვდომი",
        "аренда", "сдается", "в аренду", "арендуется", "квартиры в аренду", "сдам", "арендовать", "на аренду", "Сниму квартиру"
    ]

    # Check if text contains any of the keywords
    if not any(keyword in text_lower for keyword in keywords):
        return

    # Collect the message link
    if chat.username:  # For channels and supergroups with a username
        message_link = f"https://t.me/{chat.username}/{update.message.message_id}"
    else:
        # Fallback for groups without a username
        message_link = f"https://t.me/{chat_name}/{update.message.message_id}"

    # Collect user link
    user_link = f"https://t.me/{user.username}" if user.username else None

    # Collect data into a dictionary
    collected_data = {
        'user_link': user_link,
        'text': text,
        'message_link': message_link,
        'chat_name': chat_name,
        'message_id': update.message.message_id  # Store the message ID
    }

    try:
        # Save data to MongoDB
        await collection.insert_one(collected_data)
        logger.info("Data inserted successfully.")

        # Notify all users about the new data
        await notify_users(context, collected_data)

        # Create InlineKeyboard for user link and message link
        buttons = []
        if user_link:
            buttons.append(InlineKeyboardButton(text="User Link", url=user_link))
        buttons.append(InlineKeyboardButton(text="Message Link", url=message_link))
        reply_markup = InlineKeyboardMarkup([[*buttons]])

        # Send the confirmation message to the user's private chat
        confirmation_message = f"Text: {text}"

        await context.bot.send_message(chat_id=user.id, text=confirmation_message, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error saving data to MongoDB: {e}")

# Function to notify users about new data
async def notify_users(context: CallbackContext, data: dict) -> None:
    summary = f"Text: {data.get('text', 'No text')}"

    # Create InlineKeyboard for user link and message link
    buttons = []
    if data.get('user_link'):
        buttons.append(InlineKeyboardButton(text="User Link", url=data['user_link']))
    if data.get('message_link'):
        buttons.append(InlineKeyboardButton(text="Message Link", url=data['message_link']))
    reply_markup = InlineKeyboardMarkup([[*buttons]])

    # Retrieve all user IDs from the database
    async for user in user_collection.find():
        user_id = user["user_id"]
        # Check if this user has already been notified about this message
        if await notification_collection.find_one({"user_id": user_id, "message_id": data['message_id']}):
            continue
        
        try:
            await context.bot.send_message(chat_id=user_id, text=summary, reply_markup=reply_markup)
            logger.info(f"Notification sent to user {user_id}.")
            
            # Record the notification
            await notification_collection.insert_one({"user_id": user_id, "message_id": data['message_id']})
        except Exception as e:
            logger.error(f"Error sending notification to user {user_id}: {e}")

# Error handler
async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f"Update {update} caused error {context.error}")

def main() -> None:
    # Load Telegram bot token from environment variable
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN is not set in the environment variables.")
        raise ValueError("BOT_TOKEN is not set in the environment variables.")

    # Create the application and add handlers
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.ALL, collect_data))  # Capture any message with text or media
    
    commands = [
        BotCommand("start", "Start the bot")
    ]
    application.bot.set_my_commands(commands)
    
    # Log all errors
    application.add_error_handler(error)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
