import asyncio
import logging
import sqlite3
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import ChatAdminNotFound, UserNotParticipant, ChannelInvalid, ChannelPrivate
import config  # config.py import करें

# Logging setup
logging.basicConfig(level=logging.INFO)

app = Client("file_bot", api_id=config.API_ID, api_hash=config.API_HASH, bot_token=config.BOT_TOKEN)

# Database setup
conn = sqlite3.connect(config.DB_NAME, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT NOT NULL,
        file_name TEXT NOT NULL,
        caption TEXT,
        message_id INTEGER,
        chat_id INTEGER
    )
""")
conn.commit()

# Helper: Index last file from channel
async def index_last_file():
    try:
        async for message in app.get_chat_history(config.CHANNEL_ID, limit=1):
            if message.document or message.video or message.audio or message.photo:
                file_id = message.document.file_id if message.document else \
                          message.video.file_id if message.video else \
                          message.audio.file_id if message.audio else \
                          message.photo.file_id
                file_name = message.document.file_name if message.document else "file.jpg"
                caption = message.caption or ""
                cursor.execute("INSERT INTO files (file_id, file_name, caption, message_id, chat_id) VALUES (?, ?, ?, ?, ?)",
                               (file_id, file_name, caption, message.id, config.CHANNEL_ID))
                conn.commit()
                return f"Indexed: {file_name}"
    except (ChatAdminNotFound, UserNotParticipant, ChannelInvalid, ChannelPrivate):
        return "Error: Bot is not admin in channel or channel invalid. Add bot as admin!"
    except Exception as e:
        return f"Error indexing: {str(e)}"

# Helper: Search files
def search_files(query):
    cursor.execute("SELECT file_id, file_name, caption FROM files WHERE file_name LIKE ?", (f"%{query}%",))
    return cursor.fetchall()

# Start command
@app.on_message(filters.command("start") & filters.private)
async def start(client: Client, message: Message):
    photo_url = "https://example.com/welcome.jpg"  # Replace with your photo URL or use local file
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Help", callback_data="help")]])
    await message.reply_photo(
        photo=photo_url,
        caption="Welcome! This bot indexes files from channel. Use /index to add last file. Search files in groups!",
        reply_markup=keyboard
    )

# Index command
@app.on_message(filters.command("index") & filters.private)
async def index_cmd(client: Client, message: Message):
    result = await index_last_file()
    await message.reply(result)

# Search handler (in groups or PM, without command)
@app.on_message(filters.text & ~filters.command(["start", "index"]))
async def search_handler(client: Client, message: Message):
    query = message.text
    results = search_files(query)
    if not results:
        await message.reply("No files found!")
        return
    
    keyboard = []
    for file_id, file_name, caption in results[:10]:  # Limit to 10
        keyboard.append([InlineKeyboardButton(file_name, callback_data=f"file:{file_id}")])
    
    extra_btn = [InlineKeyboardButton("More Search", callback_data="more")]
    keyboard.append(extra_btn)
    
    await message.reply(
        f"Found {len(results)} files for '{query}':",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Callback for file button
@app.on_callback_query(filters.regex(r"^file:(.+)$"))
async def file_callback(client: Client, callback_query):
    file_id = callback_query.matches[0].group(1)
    # Fetch file details (assuming we store enough, or refetch if needed)
    cursor.execute("SELECT file_name, caption FROM files WHERE file_id=?", (file_id,))
    row = cursor.fetchone()
    if row:
        file_name, caption = row
        new_caption = f"{caption}\n\nFile: {file_name}" if caption else f"File: {file_name}"
        keyboard = [[InlineKeyboardButton("Download More", callback_data="more")]]
        await callback_query.message.reply_document(
            document=file_id,
            caption=new_caption,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    await callback_query.answer()

# Other callbacks
@app.on_callback_query(filters.regex(r"^(help|more)$"))
async def other_callback(client: Client, callback_query):
    if callback_query.data == "help":
        await callback_query.message.reply("Help: Add bot to group, search file names. Use /index in PM.")
    elif callback_query.data == "more":
        await callback_query.message.reply("Search again!")
    await callback_query.answer()

# Group add/connect: Handlers automatically work in groups

# Run bot
if __name__ == "__main__":
    app.run()
