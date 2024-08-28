import logging
import os
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from telegram import Update, Chat, BotCommand
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
user_collection = db.users  # Collection to store private chat user IDs

# PayPal setup
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET")
PAYPAL_API_BASE = "https://api-m.sandbox.paypal.com"  # Use sandbox for testing, replace with live for production

# PayPal access token
def get_paypal_access_token():
    response = requests.post(
        f"{PAYPAL_API_BASE}/v1/oauth2/token",
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        data={"grant_type": "client_credentials"},
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
    )
    response.raise_for_status()
    return response.json()["access_token"]

# PayPal create order
def create_paypal_order():
    access_token = get_paypal_access_token()
    response = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        json={
            "intent": "CAPTURE",
            "purchase_units": [{"amount": {"currency_code": "USD", "value": "10.00"}}],  # $10 for subscription
        },
    )
    response.raise_for_status()
    return response.json()

# PayPal capture order
def capture_paypal_order(order_id):
    access_token = get_paypal_access_token()
    response = requests.post(
        f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
    )
    response.raise_for_status()
    return response.json()

# Define the start command
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    chat_type = update.message.chat.type

    if chat_type == Chat.PRIVATE:
        # Check if the user is already subscribed
        if await user_collection.find_one({"user_id": user_id}):
            await update.message.reply_text("You are already subscribed!")
            return
        
        # Create a PayPal order
        order = create_paypal_order()
        approval_url = next(link["href"] for link in order["links"] if link["rel"] == "approve")

        # Send payment link to the user
        await update.message.reply_text(
            f"Please subscribe to access the bot features: {approval_url}"
        )

        # Store the order ID in the context for later verification
        context.user_data["paypal_order_id"] = order["id"]

# Function to confirm payment and add the user to the database
async def confirm_payment(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    # Retrieve the stored PayPal order ID
    order_id = context.user_data.get("paypal_order_id")
    if not order_id:
        await update.message.reply_text("No payment initiated. Please start with /start.")
        return

    try:
        # Capture the PayPal order
        capture_response = capture_paypal_order(order_id)

        if capture_response["status"] == "COMPLETED":
            # Add user ID to the database
            await user_collection.insert_one({"user_id": user_id})
            await update.message.reply_text("Payment successful! You have been subscribed.")
            logger.info(f"Added user {user_id} to the database.")
        else:
            await update.message.reply_text("Payment not completed. Please try again.")
    except Exception as e:
        logger.error(f"Error during payment capture: {e}")
        await update.message.reply_text("An error occurred during payment. Please try again.")

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
    application.add_handler(CommandHandler("confirm", confirm_payment))  # Command to confirm payment
    application.add_error_handler(error)

    # Define bot commands
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("confirm", "Confirm your payment")
    ]
    application.bot.set_my_commands(commands)

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
