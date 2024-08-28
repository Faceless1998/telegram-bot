import logging
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from telegram import Update, LabeledPrice, BotCommand, Chat
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

# Your Tranzzo credentials
TRANZZO_PROVIDER_TOKEN = os.getenv("TRANZZO_PROVIDER_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")

# Define the start command
async def start(update: Update, _: CallbackContext) -> None:
    user_id = update.message.from_user.id
    chat_type = update.message.chat.type

    if chat_type == Chat.PRIVATE:
        if await user_collection.find_one({"user_id": user_id}) is None:
            await user_collection.insert_one({"user_id": user_id})
            logger.info(f"Added user {user_id} to the database.")
    
    await update.message.reply_text("Hello! I'm a bot that collects text from groups and handles subscriptions.")

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
        "аренда", "сдается", "в аренду", "арендуется", "квартиры в аренду", "сдам", "арендовать", "на аренду", "Сниму квартиру"
    ]

    if not any(keyword in text_lower for keyword in keywords):
        return

    message_link = f"https://t.me/{chat.username}/{update.message.message_id}" if chat.username else f"https://t.me/{chat_name}/{update.message.message_id}"
    user_link = f"[{user.first_name}](https://t.me/{user.username})" if user.username else f"{user.first_name}"

    collected_data = {
        'user_link': user_link,
        'text': text,
        'message_link': message_link,
        'chat_name': chat_name,
        'message_id': update.message.message_id,
        'chat_id': update.message.chat.id
    }

    try:
        await collection.insert_one(collected_data)
        logger.info("Data inserted successfully.")
        await notify_users(context, collected_data)

        confirmation_message = (f"user link:[{user.first_name}](https://t.me/{user.username})\n"
                                f"nickname:{user.username}\n"
                                f"Text: {text}\n"
                                f"Message Link: {message_link}")
        await context.bot.send_message(chat_id=user.id, text=confirmation_message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error saving data to MongoDB: {e}")

# Function to notify users about new data
async def notify_users(context: CallbackContext, data: dict) -> None:
    summary = (f"New message from {data.get('user_link', 'Unknown')} in {data.get('chat_name', 'Unknown')}:\n"
               f"Text: {data.get('text', 'No text')}\n"
               f"Message Link: {data.get('message_link', 'No link')}\n"
               f"Message ID: {data.get('message_id', 'No ID')}\n"
               f"Chat ID: {data.get('chat_id', 'No chat ID')}\n")

    async for user in user_collection.find():
        try:
            await context.bot.send_message(chat_id=user["user_id"], text=summary, parse_mode='Markdown')
            logger.info(f"Notification sent to user {user['user_id']}.")
        except Exception as e:
            logger.error(f"Error sending notification to user {user['user_id']}: {e}")

# Function to show collected data
async def show_collected_data(update: Update, _: CallbackContext) -> None:
    if update.message.chat.type != Chat.PRIVATE:
        await update.message.reply_text("The /showdata command can only be used in a private chat with the bot.")
        return

    try:
        data_cursor = collection.find()
        num_docs = await collection.count_documents({})

        if num_docs == 0:
            await update.message.reply_text("No data collected yet.")
            return

        summary = "\n"
        async for data in data_cursor:
            summary += (f"\nMessage from {data.get('user_link', 'Unknown')} in {data.get('chat_name', 'Unknown')}:\n"
                        f"Text: {data.get('text', 'No text')}\n"
                        f"Message Link: {data.get('message_link', 'No link')}\n"
                        f"Message ID: {data.get('message_id', 'No ID')}\n"
                        f"Chat ID: {data.get('chat_id', 'No chat ID')}\n")

        max_message_length = 4096
        while len(summary) > max_message_length:
            await update.message.reply_text(summary[:max_message_length])
            summary = summary[max_message_length:]

        if summary:
            await update.message.reply_text(summary)
    except Exception as e:
        logger.error(f"Error in show_collected_data: {e}", exc_info=True)
        await update.message.reply_text("An error occurred while retrieving data.")

# Define the subscribe command
async def subscribe(update: Update, _: CallbackContext) -> None:
    chat_id = update.message.chat.id

    title = "Monthly Subscription"
    description = "Subscribe for one month"
    payload = "monthly_subscription_payload"
    provider_token = TRANZZO_PROVIDER_TOKEN
    currency = "USD"
    prices = [LabeledPrice("1 Month Subscription", 100)]  # Price in cents (e.g., 1 USD)

    await update.message.reply_invoice(
        title=title,
        description=description,
        payload=payload,
        provider_token=provider_token,
        currency=currency,
        prices=prices
    )

# Handle successful payment
async def successful_payment(update: Update, _: CallbackContext) -> None:
    payment_info = update.message.successful_payment
    user_id = update.message.from_user.id

    await user_collection.update_one(
        {"user_id": user_id},
        {"$set": {"subscription_status": "active", "subscription_end": "2024-09-30"}}  # Update end date appropriately
    )
    
    await update.message.reply_text("Thank you for your payment! Your subscription is now active.")

# Error handler
async def error(update: Update, context: CallbackContext) -> None:
    logger.warning(f"Update {update} caused error {context.error}")

def main() -> None:
    bot_token = TELEGRAM_BOT_TOKEN
    if not bot_token:
        logger.error("BOT_TOKEN is not set in the environment variables.")
        raise ValueError("BOT_TOKEN is not set in the environment variables.")

    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("showdata", show_collected_data))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    application.add_handler(MessageHandler(filters.ALL, collect_data))

    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("showdata", "Show collected data"),
        BotCommand("subscribe", "Subscribe for a monthly plan")
    ]
    application.bot.set_my_commands(commands)
    
    application.add_error_handler(error)
    application.run_polling()

if __name__ == '__main__':
    main()
