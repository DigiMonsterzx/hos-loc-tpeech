# Import necessary modules
from fastapi import FastAPI, Request
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)
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

# Define states
GENDER, LANGUAGE, VOICE, DOCUMENT, MP3_UPLOAD = range(5)

user_choices = {}

# Text-to-Speech Service
async def start_text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_choices[user_id] = {}
    
    welcome_text = (
        "Welcome to the Text-to-Speech Service!\n"
        "This service allows you to convert text in Word documents into speech.\n"
        "Please follow the steps to get started."
    )
    await update.message.reply_text(welcome_text)
    reply_markup = ReplyKeyboardMarkup([['Male', 'Female']], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text('Please choose a gender:', reply_markup=reply_markup)
    return GENDER

async def handle_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_choices[user_id]['gender'] = update.message.text.lower()
    
    reply_markup = ReplyKeyboardMarkup([['English', 'French', 'Arabic']], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text('Please choose a language:', reply_markup=reply_markup)
    return LANGUAGE

async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_choices[user_id]['language'] = update.message.text.lower()
    
    gender = user_choices[user_id]['gender']
    language = user_choices[user_id]['language']
    
    if language not in ['english', 'french', 'arabic']:
        await update.message.reply_text('Invalid language choice. Please choose from English, French, or Arabic.')
        return LANGUAGE
    
    available_voices = [voice for lang, voice in voices[gender].items() if lang == language]
    
    reply_markup = ReplyKeyboardMarkup([[voice] for voice in available_voices], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text('Please choose a voice:', reply_markup=reply_markup)
    return VOICE

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_choices[user_id]['voice'] = update.message.text
    
    # Store the user's choice in Supabase
    voice_gender_id = user_choices[user_id]['voice']
    save_voice_choice_to_db(user_id, voice_gender_id)
    
    await update.message.reply_text('Thank you! Now, please attach the Word document you want to convert to speech.')
    
    return DOCUMENT

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
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

        # Retrieve the voice_gender_id from user_choices
        voice_gender_id = user_choices[user_id]['voice']
        
        # Save details to Supabase
        save_file_details_to_db(user_id, uploaded_url, voice_gender_id)

        await update.message.reply_text('File received and uploaded!')
        return ConversationHandler.END
    else:
        await update.message.reply_text('Please send a valid Word document.')
        return DOCUMENT

# Clone Voice TTS Service
async def start_clone_voice_tts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    user_choices[user_id] = {}
    
    await update.message.reply_text('Please attach an MP3 file or provide a URL to an MP3 file.')
    return MP3_UPLOAD

async def handle_mp3_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
    file = update.message.document
    
    if file.mime_type == 'audio/mpeg':
        file_id = file.file_id
        file_info = await context.bot.get_file(file_id)

        # Download the MP3 file from Telegram servers
        file_content = requests.get(file_info.file_path).content

        # Save the file locally
        local_file_path = file.file_name
        with open(local_file_path, 'wb') as f:
            f.write(file_content)

        # Upload to Cloudinary using the original file name
        uploaded_url = upload_to_cloudinary(local_file_path)
        
        # Store the uploaded URL for later use
        user_choices[user_id]['mp3_url'] = uploaded_url
        
        await update.message.reply_text('MP3 file received! Now, please attach the Word document you want to convert to speech.')
        return DOCUMENT
    elif update.message.text and update.message.text.endswith('.mp3'):
        # Handle MP3 URL provided by the user
        user_choices[user_id]['mp3_url'] = update.message.text
        await update.message.reply_text('MP3 URL received! Now, please attach the Word document you want to convert to speech.')
        return DOCUMENT
    else:
        await update.message.reply_text('Please send a valid MP3 file or provide a valid MP3 URL.')
        return MP3_UPLOAD

async def handle_document_for_clone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.message.from_user.id
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

        # Save details to Supabase in the new table
        save_clone_voice_details_to_db(user_id, uploaded_url, user_choices[user_id]['mp3_url'])

        await update.message.reply_text('Word document received and uploaded!')
        return ConversationHandler.END
    else:
        await update.message.reply_text('Please send a valid Word document.')
        return DOCUMENT

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
    if response.data is None:
        print(f"Error updating data: {response.error}")

def save_file_details_to_db(telegram_user_id, file_url, voice_gender_id):
    data = {
        'telegram_user_id': telegram_user_id,
        'file_url': file_url,
        'status': 'Queued',
        'voice_gender_id': voice_gender_id
    }
    response = supabase.table('DbextraData').insert(data).execute()
    if response.data is None:
        print(f"Error inserting data: {response.error}")

def save_clone_voice_details_to_db(telegram_user_id, file_url, mp3_url):
    data = {
        'telegram_user_id': telegram_user_id,
        'file_url': file_url,
        'mp3_attachment': mp3_url,
        'status': 'Queued'
    }
    response = supabase.table('DbextraData_elevenlabs').insert(data).execute()
    if response.data is None:
        print(f"Error inserting data: {response.error}")

# Set up the conversation handler for Text-to-Speech
tts_handler = ConversationHandler(
    entry_points=[CommandHandler('TextToSpeech', start_text_to_speech)],
    states={
        GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_gender)],
        LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_language)],
        VOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voice)],
        DOCUMENT: [MessageHandler(filters.Document.ALL, handle_document)]
    },
    fallbacks=[]
)

# Set up the conversation handler for Clone Voice TTS
clone_voice_handler = ConversationHandler(
    entry_points=[CommandHandler('cloneVoice_tts', start_clone_voice_tts)],
    states={
        MP3_UPLOAD: [MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, handle_mp3_upload)],
        DOCUMENT: [MessageHandler(filters.Document.ALL, handle_document_for_clone)]
    },
    fallbacks=[]
)

# Add handlers to the bot application
bot_app.add_handler(tts_handler)
bot_app.add_handler(clone_voice_handler)

@app.post('/webhook')
async def webhook(request: Request):
    update = Update.de_json(await request.json(), bot_app.bot)
    await bot_app.update_queue.put(update)
    return {"status": "ok"}

if __name__ == "__main__":
    bot_app.run_polling()







# from fastapi import FastAPI, Request
# from telegram import Update, ReplyKeyboardMarkup
# from telegram.ext import (
#     ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
#     ContextTypes, filters
# )
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

# # Define states
# GENDER, LANGUAGE, VOICE, DOCUMENT = range(4)

# # Define available voices
# voices = {
#     'female': {
#         'arabic': 'ar-DZ-AminaNeural',
#         'french': 'fr-FR-DeniseNeural',
#         'english': 'en-US-AriaNeural'
#     },
#     'male': {
#         'arabic': 'ar-DZ-IsmaelNeural',
#         'french': 'fr-FR-HenriNeural',
#         'english': 'en-US-ChristopherNeural'
#     }
# }

# user_choices = {}

# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     user_id = update.message.from_user.id
#     user_choices[user_id] = {}
    
#     welcome_text = (
#         "Welcome to the Text-to-Speech Service!\n"
#         "This service allows you to convert text in Word documents into speech.\n"
#         "Please follow the steps to get started."
#     )
#     await update.message.reply_text(welcome_text)
#     reply_markup = ReplyKeyboardMarkup([['Male', 'Female']], one_time_keyboard=True, resize_keyboard=True)
#     await update.message.reply_text('Please choose a gender:', reply_markup=reply_markup)
#     return GENDER

# async def choose_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     user_id = update.message.from_user.id
#     user_choices[user_id]['gender'] = update.message.text.lower()
    
#     reply_markup = ReplyKeyboardMarkup([['English', 'French', 'Arabic']], one_time_keyboard=True, resize_keyboard=True)
#     await update.message.reply_text('Please choose a language:', reply_markup=reply_markup)
#     return LANGUAGE

# async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     user_id = update.message.from_user.id
#     user_choices[user_id]['language'] = update.message.text.lower()
    
#     gender = user_choices[user_id]['gender']
#     language = user_choices[user_id]['language']
    
#     if language not in ['english', 'french', 'arabic']:
#         await update.message.reply_text('Invalid language choice. Please choose from English, French, or Arabic.')
#         return LANGUAGE
    
#     available_voices = [voice for lang, voice in voices[gender].items() if lang == language]
    
#     reply_markup = ReplyKeyboardMarkup([[voice] for voice in available_voices], one_time_keyboard=True, resize_keyboard=True)
#     await update.message.reply_text('Please choose a voice:', reply_markup=reply_markup)
#     return VOICE

# async def choose_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     user_id = update.message.from_user.id
#     user_choices[user_id]['voice'] = update.message.text
    
#     # Store the user's choice in Supabase
#     voice_gender_id = user_choices[user_id]['voice']
#     save_voice_choice_to_db(user_id, voice_gender_id)
    
#     await update.message.reply_text('Thank you! Now, please attach the Word document you want to convert to speech.')
    
#     # Proceed to the next step
#     return DOCUMENT

# async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     user_id = update.message.from_user.id
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

#         # Retrieve the voice_gender_id from user_choices
#         voice_gender_id = user_choices[user_id]['voice']
        
#         # Save details to Supabase
#         save_file_details_to_db(user_id, uploaded_url, voice_gender_id)

#         await update.message.reply_text('File received and uploaded!')
#         return ConversationHandler.END
#     else:
#         await update.message.reply_text('Please send a valid Word document.')
#         return DOCUMENT

# def upload_to_cloudinary(file_path):
#     file_name = os.path.basename(file_path)
#     response = cloudinary.uploader.upload(file_path, resource_type="raw", folder="Queued/", public_id=file_name)
#     return response.get('secure_url')

# def save_voice_choice_to_db(telegram_user_id, voice_gender_id):
#     data = {
#         'telegram_user_id': telegram_user_id,
#         'voice_gender_id': voice_gender_id
#     }
#     response = supabase.table('DbextraData').update(data).eq('telegram_user_id', telegram_user_id).execute()
#     # Check for success based on the presence of errors in the response
#     if response.data is None:
#         print(f"Error updating data: {response.error}")

# def save_file_details_to_db(telegram_user_id, file_url, voice_gender_id):
#     data = {
#         'telegram_user_id': telegram_user_id,
#         'file_url': file_url,
#         'status': 'Queued',
#         'voice_gender_id': voice_gender_id
#     }
#     response = supabase.table('DbextraData').insert(data).execute()
#     # Check for success based on the presence of errors in the response
#     if response.data is None:
#         print(f"Error inserting data: {response.error}")

# # Set up conversation handler with states
# conv_handler = ConversationHandler(
#     entry_points=[CommandHandler("start", start)],
#     states={
#         GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_gender)],
#         LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_language)],
#         VOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_voice)],
#         DOCUMENT: [MessageHandler(filters.Document.ALL, handle_document)]
#     },
#     fallbacks=[]
# )

# bot_app.add_handler(conv_handler)

# @app.post("/webhook")
# async def webhook(request: Request):
#     update = Update.de_json(await request.json(), bot_app.bot)
#     await bot_app.initialize()
#     await bot_app.process_update(update)
#     return {"status": "ok"}

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)






# # if __name__ == "__main__":
# #     import uvicorn
# #     uvicorn.run(app, host="0.0.0.0", port=8000)


