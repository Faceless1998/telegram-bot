import logging
import os
from telegram import Update, Message
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from pymongo import MongoClient
from pymongo.collection import Collection
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Debugging statements
print(f"MONGO_URI: {os.getenv('MONGO_URI')}")
print(f"BOT_TOKEN: {os.getenv('BOT_TOKEN')}")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB setup
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client.telegram_bot
collection: Collection = db.collected_data

# Define the start command
async def start(update: Update, _: CallbackContext) -> None:
    await update.message.reply_text("Hello! I'm a bot that collects text from groups.")

# Function to collect data from the group
async def collect_data(update: Update, _: CallbackContext) -> None:
    user = update.message.from_user  # Get the user who sent the message
    chat = update.message.chat  # Get the chat where the message was sent
    chat_name = chat.title if chat.title else chat.username or "Private Chat"

    # Collect the message text or caption
    text = update.message.text if update.message.text else update.message.caption

    # If both text and caption are None, return early
    if not text:
        return

    # Collect the message link
    if chat.username:  # For channels and supergroups with a username
        message_link = f"https://t.me/{chat.username}/{update.message.message_id}"
    else:
        # Fallback for groups without a username
        message_link = f"https://t.me/{chat_name}/{update.message.message_id}"

    # Collect user link
    user_link = f"[{user.first_name}](https://t.me/{user.username})"

    # Collect data into a dictionary
    collected_data = {
        'user_link': user_link,
        'text': text,
        'message_link': message_link,
        'chat_name': chat_name,
        'message_id': update.message.message_id,  # Store the message ID
        'chat_id': chat_name # Store the chat ID
    }

    # Save data to MongoDB
    collection.insert_one(collected_data)

    # Reply with a confirmation message

# Function to retrieve and display all collected data
async def show_collected_data(update: Update, _: CallbackContext) -> None:
    data_cursor = collection.find()
    
    if data_cursor.count_documents({}) == 0:
        await update.message.reply_text("No data collected yet.")
        return

    summary = "Collected Data:\n"
    for idx, data in enumerate(data_cursor, start=1):
        summary += f"\n{idx}. Message from {data['user_link']} in {data['chat_name']}:\nText: {data['text']}\nMessage Link: {data['message_link']}\nMessage ID: {data['message_id']}\nChat ID: {data['chat_id']}"
       

# Error handler
async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f"Update {update} caused error {context.error}")

def main() -> None:
    # Load Telegram bot token from environment variable
    bot_token = os.getenv("BOT_TOKEN")

    # Check if bot_token is loaded
    if not bot_token:
        raise ValueError("Bot token is not set in the environment variables")

    # Create the application and add handlers
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("showdata", show_collected_data))  # Command to show collected data
    application.add_handler(MessageHandler(filters.ALL, collect_data))  # Changed filter to ALL to capture any message with text or media
    
    # Log all errors
    application.add_error_handler(error)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
