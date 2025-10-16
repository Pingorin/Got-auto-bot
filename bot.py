#!/usr/bin/env python3
import logging
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import ChatAdminRequired, UserNotParticipant, ChannelInvalid, ChannelPrivate, BadRequest, Forbidden

# Load env
load_dotenv()

# Config from env with validation
required_env = ["API_ID", "API_HASH", "BOT_TOKEN", "CHANNEL_ID", "DATABASE_URL"]
missing = [var for var in required_env if not os.getenv(var)]
if missing:
    raise ValueError(f"Missing env vars: {', '.join(missing)}. Set them in Render dashboard!")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")
DB_NAME = os.getenv("DB_NAME", "filebot_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "files")
PHOTO_URL = os.getenv("PHOTO_URL", "https://example.com/welcome.jpg")  # Add to env for custom photo

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client("file_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# MongoDB setup with error handling
try:
    mongo_client = MongoClient(DATABASE_URL, serverSelectionTimeoutMS=5000)
    mongo_client.server_info()  # Test connection
    db = mongo_client[DB_NAME]
    collection = db[COLLECTION_NAME]
    collection.create_index("file_name")
    logger.info("MongoDB connected successfully.")
except Exception as e:
    logger.error(f"MongoDB connection failed: {str(e)}")
    raise

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
    recent except ChatAdminRequired:
        logger.error("Bot requires admin privileges.")
        return "Error: Bot needs admin rights in channel!"
    except UserNotParticipant:
        logger.error("Bot not participant.")
        return "Error: Add bot to channel!"
    except (ChannelInvalid, ChannelPrivate, BadRequest, Forbidden) as e:
        logger.error(f"Channel error: {str(e)}")
        return f"Error: Channel issue - {str(e)}"
    except Exception as e:
        logger.error(f"Indexing error: {str(e)}")
        return f"Error: {str(e)}"

# Helper: Search files
def search_files(query):
    if not query:
        return []
    regex = {"$regex": query, "$options": "i"}
    results = list(collection.find({"file_name": regex}).limit(10))
    return [(r["file_id"], r["file_name"], r["caption"]) for r in results]

# Start command
@app.on_message(filters.command("start") & filters.private)
async def start(client: Client, message: Message):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Help", callback_data="help")]])
    try:
        await message.reply_photo(
            photo=PHOTO_URL,
            caption="Welcome to File Bot! Use /index to index files. Search in groups.",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Photo send failed: {str(e)}. Sending text instead2.")
        await message.reply(
            "Welcome to File Bot! Use /index to index files. Search in groups.",
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
    for file_id, file_name, _ in results:
        keyboard.append([InlineKeyboardButton(file_name, callback_data=f"file:{file_id}:{file_name}")])
    
    if total > 10:
        keyboard.append([InlineKeyboardButton("Show More", callback_data="more")])
    
    await message.reply(
        f"Found {total} files for '{query}' (showing 10):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Callback for file
@app.on_callback_query(filters.regex(r"^file:(.+):(.+)$"))
async def file_callback(client: Client, callback_query):
    try:
        file_id = callback_query.matches[0].group(1)
        file_name = callback_query.matches[0].group(2)
    except (IndexError, AttributeError):
        await callback_query.answer("Invalid file data!")
        return
    
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
            await callback_query.answer("File sent!")
        except Exception as e:
            await callback_query.message.reply(f"Error sending file: {str(e)}")
            await callback_query.answer("Send failed!")
    else:
        await callback_query.message.reply("File not found in database!")
        await callback_query.answer("Error!")

# Other callbacks
@app.on_callback_query(filters.regex(r"^(help|more)$"))
async def other_callback(client: Client, callback_query):
    if callback_query.data == "help":
        await callback_query.message.reply("Help: /start - Welcome, /index - Index last file. Search file names directly.")
    elif callback_query.data == "more":
        await callback_query.message.reply("Type another file name to search!")
    await callback_query.answer()

# Run bot
if __name__ == "__main__":
    try:
        app.start()
        logger.info("Bot is running...")
        idle()
    except Exception as e:
        logger.error(f"Bot crashed: {str(e)}")
    finally:
        app.stop()
        logger.info("Bot stopped.")
