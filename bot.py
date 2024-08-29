import logging
import os
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from telegram import (
    Update,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
)

# Load environment variables from .env file
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
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

# Define service keywords
service_keywords = {
    "Renters Real Estate": [
        "for rent",
        "rental",
        "rent",
        "available for rent",
        "leasing",
        "rental property",
        "for lease",
    ],
    "Sellers Real Estate": ["sell", "selling", "property for sale", "real estate sale"],
    "Landlords Real Estate": [
        "landlord",
        "landlord's property",
        "property available for rent",
    ],
    # Add keywords for other services
}

# Initial service state (default is off)
service_state = {
    service: False
    for service in [
        "Renters Real Estate",
        "Sellers Real Estate",
        "Landlords Real Estate",
        "Currency and Crypto Exchange",
        "Buyers Real Estate",
        "Residence Permit",
        "Short-Term Renters",
        "Room or Hostel Renters",
        "Owners Real Estate",
        "AI - Renters Real Estate",
        "Renters Cars",
        "Landlords Cars",
        "Transfer",
        "Bike Rentals",
        "Yacht Rentals",
        "Excursions",
        "Massage",
        "Cleaning",
        "Photography",
        "Insurance",
        "Manicure",
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
            trial_end_date = (datetime.utcnow() + timedelta(days=3)).strftime(
                "%Y-%m-%d"
            )

            await user_collection.insert_one(
                {
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "user_id": user_id,
                    "status": True,  # Set status to True for active
                    "trial_end_date": trial_end_date,
                    "services": [],  # Store the selected services
                }
            )
            logger.info(f"Added user {user_id} to the database with status 'True'.")
            await update.message.reply_text(
                "Hello! I'm a bot that collects text from groups. You have a 3-day free trial."
            )
        else:
            logger.info(f"User {user_id} already registered.")
            await update.message.reply_text(
                "You have already started. I'm here to collect text from groups."
            )


async def services(update: Update, _: CallbackContext) -> None:
    reply_markup = generate_service_keyboard()
    await update.message.reply_text(
        "Please choose a service:", reply_markup=reply_markup
    )


async def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user = query.from_user
    user_data = await user_collection.find_one({"user_id": user.id})

    service_name, status = query.data.rsplit("_", 1)

    if status == "on":
        service_state[service_name] = True

        # Update user's selected services and adjust trial period
        selected_services = user_data.get("services", [])
        selected_services.append(service_name)

        if len(selected_services) == 1:
            trial_end_date = (datetime.utcnow() + timedelta(days=3)).strftime(
                "%Y-%m-%d"
            )
        else:
            trial_end_date = (
                datetime.utcnow()
                .replace(hour=23, minute=59, second=59)
                .strftime("%Y-%m-%d %H:%M:%S")
            )

        await user_collection.update_one(
            {"user_id": user.id},
            {"$set": {"services": selected_services, "trial_end_date": trial_end_date}},
        )
    elif status == "off":
        service_state[service_name] = False

        # Update user's selected services
        selected_services = user_data.get("services", [])
        if service_name in selected_services:
            selected_services.remove(service_name)

        await user_collection.update_one(
            {"user_id": user.id}, {"$set": {"services": selected_services}}
        )

    await query.answer()
    await query.edit_message_text(
        text="choose service", reply_markup=generate_service_keyboard()
    )


async def collect_data(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    chat = update.message.chat
    chat_name = chat.title if chat.title else chat.username or "Private Chat"
    text = update.message.text if update.message.text else update.message.caption

    if not text:
        return

    text_lower = text.lower()

    # Fetch user's selected services
    user_data = await user_collection.find_one({"user_id": user.id})
    selected_services = user_data.get("services", [])

    # Check if the text matches any keyword from the selected services
    matched_keywords = []
    for service in selected_services:
        keywords = service_keywords.get(service, [])
        if any(keyword in text_lower for keyword in keywords):
            matched_keywords.append(service)

    if not matched_keywords:
        return

    if chat.username:
        message_link = f"https://t.me/{chat.username}/{update.message.message_id}"
    else:
        message_link = f"https://t.me/{chat_name}/{update.message.message_id}"

    user_link = f"https://t.me/{user.username}" if user.username else None

    collected_data = {
        "user_link": user_link,
        "text": text,
        "message_link": message_link,
        "chat_name": chat_name,
        "message_id": update.message.message_id,
        "matched_services": matched_keywords,
    }

    try:
        await collection.insert_one(collected_data)
        logger.info("Data inserted successfully.")
        await notify_users(context, collected_data)
    except Exception as e:
        logger.error(f"Error saving data to MongoDB: {e}")


async def notify_users(context: CallbackContext, data: dict) -> None:
    summary = f"{data.get('text', 'No text')}"
    buttons = []
    if data.get("user_link"):
        buttons.append(InlineKeyboardButton(text="User Link", url=data["user_link"]))
    if data.get("message_link"):
        buttons.append(
            InlineKeyboardButton(text="Message Link", url=data["message_link"])
        )
    reply_markup = InlineKeyboardMarkup([[*buttons]])

    async for user in user_collection.find(
        {"status": True}
    ):  # Only notify active users
        user_id = user["user_id"]
        trial_end_date_str = user.get("trial_end_date")
        if trial_end_date_str:
            try:
                trial_end_date = datetime.strptime(
                    trial_end_date_str, "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                trial_end_date = datetime.strptime(trial_end_date_str, "%Y-%m-%d")
            if datetime.utcnow() >= trial_end_date:
                await user_collection.update_one(
                    {"user_id": user_id}, {"$set": {"status": False}}
                )
                logger.info(
                    f"User {user_id} trial period ended. Status changed to 'False'."
                )
                continue

        if await notification_collection.find_one(
            {"user_id": user_id, "message_id": data["message_id"]}
        ):
            continue

        # Notify users based on their selected services
        user_services = user.get("services", [])
        if any(
            service in data.get("matched_services", []) for service in user_services
        ):
            try:
                await context.bot.send_message(
                    chat_id=user_id, text=summary, reply_markup=reply_markup
                )
                logger.info(f"Notification sent to user {user_id}.")
                await notification_collection.insert_one(
                    {"user_id": user_id, "message_id": data["message_id"]}
                )
            except Exception as e:
                logger.error(f"Error sending notification to user {user_id}: {e}")


# Error handler
async def error(update: Update, context: CallbackContext) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


def main() -> None:
    """Run the bot."""
    application = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("services", services))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, collect_data))

    # Log all errors
    application.add_error_handler(error)

    # Run the bot
    application.run_polling()


if __name__ == "__main__":
    main()
