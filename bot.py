#!/usr/bin/env python3
import asyncio
import logging
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from pyrogram import Client, filters, idle  # Added idle here
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import ChatAdminRequired, UserNotParticipant, ChannelInvalid, ChannelPrivate, BadRequest, Forbidden

# Load env
load_dotenv()

# Config from env
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME", "filebot_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "files")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client("file_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB setup
mongo_client = MongoClient(DATABASE_URL)
db = mongo_client[DB_NAME]
collection = db[YCOLLECTION_NAME]

# Ensure index for faster search
collection.create_index("file_name")

# Helper: Index last file from channel
async def index_last_file():
    try:
        async for message in app.get_chat_history(CHANNEL_ID, limit=1):
            if message.document or message.video or message.audio or message.photo:
                file_id = message.document.file_id if message.document else \
                          message.video.file_id if message.video else \
                          message.audio.file_id if message.audio else \
                          message.photo.file_id if message.photo else None
                if not file_id:
                    return "No media file found in last message."
                file_name = message.document.file_name if message.document else \
                            message.video.file_name if message.video else \
                            message.audio.file_name if message.audio else "photo.jpg"
                caption = message.caption or ""
                
                # Check duplicate and insert
                if collection.find_one({"file_id": file_id}):
                    return f"Already indexed: {file_name}"
                
                collection.insert_one({
                    "file_id": file_id,
                    "file_name": file_name,
                    "caption": caption,
                    "message_id": message.id,
                    "chat_id": CHANNEL_ID
                })
                return f"Indexed: {file_name}"
    except ChatAdminRequired:
        logger.error("Bot requires admin privileges in the channel.")
        return "Error: Bot needs admin rights in the channel to access history. Promote bot to admin!"
    except UserNotParticipant:
        logger.error("Bot is not a participant in the channel.")
        return "Error: Bot is not added to the channel. Add bot first!"
    except (ChannelInvalid, ChannelPrivate

, BadRequest, Forbidden) as e:
        logger.error(f"Channel access error: {str(e)}")
        return f"Error: Invalid or private channel/access denied: {str(e)}. Check CHANNEL_ID and bot permissions!"
    except Exception as e:
        logger.error(f"Unexpected error during indexing: {str(e)}")
        return f"Error indexing: {str(e)}"

# Helper: Search files
def search_files(query):
    regex = {"$regex": query, "$options": "i"}  # Case-insensitive
    results = list(collection.find({"file_name": regex}).limit(10))
    return [(r["file_id"], r["file_name"], r["caption"]) for r in results]

# Start command
@app.on_message(filters.command("start") & filters.private)
async def start(client: Client, message: Message):
    photo_url = "https://example.com/welcome.jpg"  # Replace
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Help", callback_data="help")]])
    await message.reply_photo(
        photo=photo_url,
        caption="Welcome to File Bot! Use /index to index files. Search in groups.",
        reply_markup=keyboard
    )

# Index command
@app.on_message(filters.command("index") & filters.private)
async def index_cmd(client: Client, message: Message):
    result = await index_last_file()
    await message.reply(result)

# Search handler
@app.on_message(filters.text & ~filters.command(["start", "index"]))
async def search_handler(client: Client, message: Message):
    query = message.text.strip()
    results = search_files(query)
    if not results:
        await message.reply("No matching files found!")
        return
    
    total = collection.count_documents({"file_name": {"$regex": query, "$options": "i"}})
    keyboard = []
    for file_id, file_name, caption in results:
        keyboard.append([InlineKeyboardButton(file_name, callback_data=f"file:{file_id}:{file_name}")])
    
    if total > 10:
        keyboard.append([InlineKeyboardButton("Show More", callback_data="more")])
    
    await message.reply(
        f"Found {total} files for '{query}' (showing 10):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Callback for file
@app.on_callback_query(filters.regex(r r"^file:(.+):(.+)$"))
async def file_callback(client: Client, callback_query):
    file_id = callback_query.matches[0].group(1)
    file_name = callback_query.matches[0].group(2)
    doc = collection.find_one({"file_id": file_id})
    if doc:
        caption = doc["caption"]
        new_caption = f"{caption}\n\nFile: {file_name}" if caption else f"File: {file_name}"
        keyboard = [[InlineKeyboardButton("Search More", callback_data="more")]]
        try:
            await client.send_document(
                chat_id=callback_query.from_user.id,
                document=file_id,
                caption=new_caption,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await callback_query.message.reply(f"Error sending file: {str(e)}")
    else:
        await callback_query.message.reply("File not found in database!")
    await callback_query.answer("File sent!" if doc else "Error!")

# Other callbacks
@app.on_callback_query(filters.regex(r"^(help|more)$"))
async def other_callback(client: Client, callback_query):
    if callback_query.data == "help":
        await callback_query.message.reply("Help: /start - Welcome, /index - Index last file. Search file names directly.")
    elif callback_query.data == "more":
        await callback_query.message.reply("Type another file name to search!")
    await callback_query.answer()

# Run bot with idle
if __name__ == "__main__":
    try:
        app.start()
        logger.info("Bot is running...")
        idle()  # Keeps the bot alive and handling updates
    except Exception as e:
        logger.error(f"Bot crashed: {str(e)}")
    finally:
        app.stop()
        logger.info("Bot stopped.")
