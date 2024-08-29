import logging
import os
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from telegram import Update, Chat, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

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

# Initial service state (default is off)
service_state = {
    service: False for service in [
        "Renters Real Estate", "Sellers Real Estate", "Landlords Real Estate",
        "Currency and Crypto Exchange", "Buyers Real Estate", "Residence Permit",
        "Short-Term Renters", "Room or Hostel Renters", "Owners Real Estate",
        "AI - Renters Real Estate", "Renters Cars", "Landlords Cars", "Transfer",
        "Bike Rentals", "Yacht Rentals", "Excursions", "Massage", "Cleaning",
        "Photography", "Insurance", "Manicure"
    ]
}

def generate_service_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    for service, is_on in service_state.items():
        color = "🟢" if is_on else "🔴"
        button_text = f"{color} {service}"
        callback_data = f"{service}_on" if not is_on else f"{service}_off"
        button = InlineKeyboardButton(button_text, callback_data=callback_data)
        keyboard.append([button])
    return InlineKeyboardMarkup(keyboard)

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

async def services(update: Update, _: CallbackContext) -> None:
    reply_markup = generate_service_keyboard()
    await update.message.reply_text("Please choose a service:", reply_markup=reply_markup)

async def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    service_name, status = query.data.rsplit('_', 1)

    if status == "on":
        service_state[service_name] = True
        response_text = f"{service_name} is now enabled. 🟢"
        callback_data = f"{service_name}_off"
    elif status == "off":
        service_state[service_name] = False
        response_text = f"{service_name} is now disabled. 🔴"
        callback_data = f"{service_name}_on"

    await query.answer()
    await query.edit_message_text(text=response_text, reply_markup=generate_service_keyboard())

# Function to collect data from the group
async def collect_data(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    chat = update.message.chat
    chat_name = chat.title if chat.title else chat.username or "Private Chat"
    text = update.message.text if update.message.text else update.message.caption

    if not text:
        return

    text_lower = text.lower()

    # Keywords for each service
    service_keywords = {
        "Renters Real Estate": ["for rent", "rental", "rent", "available for rent", "leasing", "rental property", "for lease", "rental unit"],
        "Sellers Real Estate": ["for sale", "selling", "buy property", "house for sale", "property for sale"],
        "Landlords Real Estate": ["landlord", "landlord needed", "rent out", "property management"],
        "Currency and Crypto Exchange": ["currency exchange", "crypto exchange", "buy bitcoin", "sell bitcoin", "forex", "crypto trading"],
        "Buyers Real Estate": ["buy house", "buy property", "property purchase", "real estate investment"],
        "Residence Permit": ["residence permit", "visa", "immigration", "work permit", "residency"],
        "Short-Term Renters": ["short-term rental", "vacation rental", "holiday home", "airbnb", "temporary accommodation"],
        "Room or Hostel Renters": ["room for rent", "hostel", "shared accommodation", "hostel vacancy", "roommate needed"],
        "Owners Real Estate": ["property owner", "own property", "real estate owner", "own house", "property portfolio"],
        "AI - Renters Real Estate": ["ai rental", "ai real estate", "smart rental", "ai property management"],
        "Renters Cars": ["car rental", "rent a car", "car lease", "vehicle rental", "rental car available"],
        "Landlords Cars": ["rent out car", "car lease", "car available for rent"],
        "Transfer": ["airport transfer", "shuttle service", "transport service", "pickup and drop", "travel transfer"],
        "Bike Rentals": ["bike rental", "rent a bike", "bicycle rental", "bike hire"],
        "Yacht Rentals": ["yacht rental", "rent a yacht", "boat rental", "yacht hire", "luxury boat rental"],
        "Excursions": ["excursion", "guided tour", "day trip", "sightseeing tour", "tourist attraction"],
        "Massage": ["massage service", "spa treatment", "therapeutic massage", "relaxation massage"],
        "Cleaning": ["cleaning service", "house cleaning", "office cleaning", "maid service", "deep cleaning"],
        "Photography": ["photography service", "event photography", "portrait photography", "photo shoot", "professional photographer"],
        "Insurance": ["insurance", "life insurance", "health insurance", "car insurance", "property insurance"],
        "Manicure": ["manicure", "nail salon", "nail treatment", "nail care", "nail art"],
    }

    # Check if any service keywords are present in the message
    matched_services = [service for service, keywords in service_keywords.items() if any(keyword in text_lower for keyword in keywords)]

    if not matched_services:
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
        'message_id': update.message.message_id,
        'services': matched_services  # Store the matched services
    }

    try:
        await collection.insert_one(collected_data)
        logger.info(f"Data inserted successfully with matched services: {matched_services}")
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
                await user_collection.update_one({"user_id": user_id}, {"$set": {"status": False}})
                continue
        try:
            await context.bot.send_message(chat_id=user_id, text=summary, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

async def main() -> None:
    # Create the Application and pass it your bot's token
    application = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("services", services))

    # on non command i.e message - collect data
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_data))

    # on callback from inline buttons
    application.add_handler(CallbackQueryHandler(button))

    # Run the bot
    await application.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
