from fastapi import FastAPI, Request
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import os
import requests
import cloudinary
import cloudinary.uploader
from supabase import create_client, Client
import asyncio

app = FastAPI()

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

# Initialize the Telegram bot application
bot_app = ApplicationBuilder().token(TOKEN).build()

# Define available voices
voices = {
    'female': {
        'arabic': 'ar-DZ-AminaNeural',
        'french': 'fr-FR-DeniseNeural',
        'english': 'en-US-AriaNeural'
    },
    'male': {
        'arabic': 'ar-DZ-IsmaelNeural',
        'french': 'fr-FR-HenriNeural',
        'english': 'en-US-ChristopherNeural'
    }
}

user_choices = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_choices[user_id] = {}
    
    welcome_text = (
        "Welcome to the Text-to-Speech Service!\n"
        "This service allows you to convert text in Word documents into speech.\n"
        "Please follow the steps to get started."
    )
    await update.message.reply_text(welcome_text)
    await ask_for_gender(update, context)

async def ask_for_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply_markup = ReplyKeyboardMarkup([['Male', 'Female']], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text('Please choose a gender:', reply_markup=reply_markup)

async def ask_for_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_choices[user_id]['gender'] = update.message.text.lower()
    
    reply_markup = ReplyKeyboardMarkup([['English', 'French', 'Arabic']], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text('Please choose a language:', reply_markup=reply_markup)

async def ask_for_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_choices[user_id]['language'] = update.message.text.lower()
    
    gender = user_choices[user_id]['gender']
    language = user_choices[user_id]['language']
    
    if language == 'english':
        language_code = 'english'
    elif language == 'french':
        language_code = 'french'
    elif language == 'arabic':
        language_code = 'arabic'
    else:
        await update.message.reply_text('Invalid language choice. Please start over.')
        return
    
    available_voices = [voice for lang, voice in voices[gender].items() if lang == language_code]
    
    reply_markup = ReplyKeyboardMarkup([[voice] for voice in available_voices], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text('Please choose a voice:', reply_markup=reply_markup)

async def handle_voice_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_choices[user_id]['voice'] = update.message.text
    
    # Store the user's choice in Supabase
    voice_gender_id = user_choices[user_id]['voice']
    save_voice_choice_to_db(user_id, voice_gender_id)
    
    await update.message.reply_text('Thank you! Now, please attach the Word document you want to convert to speech.')

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    file = update.message.document
    if file.mime_type in ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
        file_id = file.file_id
        file_info = await context.bot.get_file(file_id)

        # Download the file from Telegram servers
        file_content = requests.get(file_info.file_path).content

        # Save the file locally with its original name (optional)
        local_file_path = file.file_name
        with open(local_file_path, 'wb') as f:
            f.write(file_content)

        # Upload to Cloudinary using the original file name
        uploaded_url = upload_to_cloudinary(local_file_path)

        # Save details to Supabase
        save_file_details_to_db(update.message.from_user.id, uploaded_url)

        await update.message.reply_text('File received and uploaded!')
    else:
        await update.message.reply_text('Please send a valid Word document.')

def upload_to_cloudinary(file_path):
    file_name = os.path.basename(file_path)
    response = cloudinary.uploader.upload(file_path, resource_type="raw", folder="Queued/", public_id=file_name)
    return response.get('secure_url')

def save_voice_choice_to_db(telegram_user_id, voice_gender_id):
    data = {
        'telegram_user_id': telegram_user_id,
        'voice_gender_id': voice_gender_id
    }
    response = supabase.table('DbextraData').update(data).eq('telegram_user_id', telegram_user_id).execute()
    if response.status_code != 200:
        print(f"Error updating data: {response.data}")

def save_file_details_to_db(telegram_user_id, file_url):
    data = {
        'telegram_user_id': telegram_user_id,
        'file_url': file_url,
        'status': 'Queued',
    }
    response = supabase.table('DbextraData').insert(data).execute()
    if response.status_code != 201:
        print(f"Error inserting data: {response.data}")

# Set up command handlers
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_for_language))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_for_voice))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voice_selection))
bot_app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

@app.post("/webhook")
async def webhook(request: Request):
    update = Update.de_json(await request.json(), bot_app.bot)
    await bot_app.initialize()
    await bot_app.process_update(update)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)




# from fastapi import FastAPI, Request
# from telegram import Update
# from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
# import os
# import requests
# import cloudinary
# import cloudinary.uploader
# from supabase import create_client, Client
# import asyncio

# app = FastAPI()

# # Load environment variables
# TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
# CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
# API_KEY = os.getenv('CLOUDINARY_API_KEY')
# API_SECRET = os.getenv('CLOUDINARY_API_SECRET')
# SUPABASE_URL = os.getenv('SUPABASE_URL')
# SUPABASE_API_KEY = os.getenv('SUPABASE_API_KEY')

# # Configure Cloudinary with your credentials
# cloudinary.config(
#     cloud_name=CLOUD_NAME,
#     api_key=API_KEY,
#     api_secret=API_SECRET
# )

# # Initialize Supabase client
# supabase: Client = create_client(SUPABASE_URL, SUPABASE_API_KEY)

# # Initialize the Telegram bot application
# bot_app = ApplicationBuilder().token(TOKEN).build()

# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     await update.message.reply_text('Hi! Send me a Word document.')

# async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     file = update.message.document
#     if file.mime_type in ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
#         file_id = file.file_id
#         file_info = await context.bot.get_file(file_id)

#         # Download the file from Telegram servers
#         file_content = requests.get(file_info.file_path).content

#         # Save the file locally with its original name (optional)
#         local_file_path = file.file_name
#         with open(local_file_path, 'wb') as f:
#             f.write(file_content)

#         # Upload to Cloudinary using the original file name
#         uploaded_url = upload_to_cloudinary(local_file_path)

#         # Save details to Supabase
#         save_file_details_to_db(update.message.from_user.id, uploaded_url)

#         await update.message.reply_text('File received and uploaded!')
#     else:
#         await update.message.reply_text('Please send a valid Word document.')

# def upload_to_cloudinary(file_path):
#     file_name = os.path.basename(file_path)
#     response = cloudinary.uploader.upload(file_path, resource_type="raw", folder="Queued/", public_id=file_name)
#     return response.get('secure_url')

# def save_file_details_to_db(telegram_user_id, file_url):
#     data = {
#         'telegram_user_id': telegram_user_id,
#         'file_url': file_url,
#         'status': 'Queued',
#     }
#     response = supabase.table('DbextraData').insert(data).execute()
#     if response.status_code != 201:
#         print(f"Error inserting data: {response.data}")

# # Set up command handlers
# bot_app.add_handler(CommandHandler("start", start))
# bot_app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

# @app.post("/webhook")
# async def webhook(request: Request):
#     update = Update.de_json(await request.json(), bot_app.bot)
#     await bot_app.initialize()
#     await bot_app.process_update(update)
#     return {"status": "ok"}

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)


