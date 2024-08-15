from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import os
import requests
import cloudinary
import cloudinary.uploader
from supabase import create_client, Client

app = Flask(__name__)

# Load environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
API_KEY = os.getenv('CLOUDINARY_API_KEY')
API_SECRET = os.getenv('CLOUDINARY_API_SECRET')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_API_KEY = os.getenv('SUPABASE_API_KEY')

# Configure Cloudinary with your credentials
cloudinary.config(
    cloud_name=CLOUD_NAME,
    api_key=API_KEY,
    api_secret=API_SECRET
)

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_API_KEY)

# Initialize the bot updater and dispatcher
updater = Update(TOKEN)
dispatcher = updater.dispatcher

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Hi! Send me a Word document.')

def handle_document(update: Update, context: CallbackContext) -> None:
    file = update.message.document
    if file.mime_type in ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
        file_id = file.file_id
        file_info = context.bot.get_file(file_id)
        file_path = file_info.file_path
        # Download the file from Telegram servers
        file_content = requests.get(file_info.file_path).content

        # Save the file locally (optional)
        with open(file.file_name, 'wb') as f:
            f.write(file_content)

        # Upload to Cloudinary
        uploaded_url = upload_to_cloudinary(file.file_name, file_content)

        # Save details to Supabase
        save_file_details_to_db(update.message.from_user.id, uploaded_url)

        update.message.reply_text('File received and uploaded!')

    else:
        update.message.reply_text('Please send a valid Word document.')

def upload_to_cloudinary(file_name, file_content):
    response = cloudinary.uploader.upload(file_content, resource_type="raw", folder="Queued/")
    return response.get('secure_url')

def save_file_details_to_db(telegram_user_id, file_url):
    data = {
        'telegram_user_id': telegram_user_id,
        'file_url': file_url,
        'status': 'Queued',
    }
    response = supabase.table('files').insert(data).execute()
    if response.status_code != 201:
        print(f"Error inserting data: {response.data}")

# Set up command handlers
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.document, handle_document))

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), updater.bot)
    dispatcher.process_update(update)
    return 'ok'

if __name__ == '__main__':
    # Start Flask app with Gunicorn
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
