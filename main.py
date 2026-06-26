import asyncio
import os
import tempfile
import json
import logging
import traceback
import sys
from datetime import datetime
from typing import Dict

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from dotenv import load_dotenv
import pymongo

from config import Config
from utils import (
    setup_logging, ProgressTracker, format_file_size, format_time,
    calculate_eta, create_progress_bar, update_progress_message
)
from parser import parse_pdf

load_dotenv()

logger = setup_logging()

# MongoDB
try:
    mongo_client = pymongo.MongoClient(Config.MONGO_URI)
    db = mongo_client[Config.DATABASE_NAME]
    sessions_collection = db["user_sessions"]
    conversions_collection = db["conversions"]
    logger.info("✅ MongoDB connected")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    sessions_collection = None
    conversions_collection = None

app = Client("pdf_bot", api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=Config.BOT_TOKEN)

user_sessions: Dict[int, Dict] = {}
active_conversions: Dict[int, Dict] = {}

# ---------- Command Handlers ----------
@app.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    await message.reply_text(
        "🌟 **PDF → JSON Converter Bot**\n\n"
        "I convert SSC PDFs to structured JSON.\n"
        "Use /pdf2json to start.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Start", callback_data="start_convert")]
        ])
    )

@app.on_message(filters.command("pdf2json"))
async def pdf2json_cmd(client, message: Message):
    user_id = message.from_user.id
    if user_id in active_conversions:
        await message.reply_text("⚠️ You have an active conversion. Use /cancel to stop it.")
        return
    user_sessions[user_id] = {"state": "waiting_for_pdf", "timestamp": datetime.now()}
    await message.reply_text(
        "📤 **Upload your PDF** (max 50MB) or forward one.\n"
        "I'll extract all questions and generate JSON.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ])
    )

@app.on_message(filters.command("cancel"))
async def cancel_cmd(client, message: Message):
    user_id = message.from_user.id
    if user_id in active_conversions:
        del active_conversions[user_id]
    if user_id in user_sessions:
        del user_sessions[user_id]
    await message.reply_text("✅ Cancelled.", parse_mode=ParseMode.HTML)

@app.on_message(filters.document & ~filters.command(["start", "pdf2json", "cancel"]))
async def handle_pdf(client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_sessions or user_sessions[user_id].get("state") != "waiting_for_pdf":
        await message.reply_text("⚠️ Please use /pdf2json first.", parse_mode=ParseMode.HTML)
        return

    doc = message.document
    if not doc.file_name.lower().endswith(".pdf"):
        await message.reply_text("❌ Only PDF files are supported.", parse_mode=ParseMode.HTML)
        return
    if doc.file_size > 50 * 1024 * 1024:
        await message.reply_text("❌ File too large (max 50MB).", parse_mode=ParseMode.HTML)
        return

    progress = ProgressTracker()
    progress.start()
    active_conversions[user_id] = {
        "current_step": "Downloading...",
        "pages_processed": 0,
        "total_pages": 0,
        "questions_found": 0,
        "start_time": datetime.now(),
        "recent_logs": [],
        "progress": progress
    }

    status_msg = await message.reply_text(
        "⏳ **Processing...**\nPlease wait.",
        parse_mode=ParseMode.HTML
    )

    temp_path = None
    json_path = None
    try:
        # Download PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            temp_path = f.name
            await client.download_media(message, file_name=temp_path)

        # Parse PDF using your logic
        result = await parse_pdf(
            pdf_path=temp_path,
            progress_callback=lambda step, total, msg: update_progress(
                status_msg, user_id, step, total, msg
            )
        )

        questions_data = result["questions"]
        total_q = len(questions_data)

        # Build final JSON
        output = {
            "schemaVersion": "1.0",
            "pdfName": doc.file_name.replace(".pdf", ""),
            "topic": "Static GK",
            "topicCode": "SGK",
            "totalQuestions": total_q,
            "questions": questions_data
        }

        # Save JSON
        json_filename = f"{doc.file_name.replace('.pdf', '').replace(' ', '_')}_{total_q}.json"
        json_path = os.path.join(tempfile.gettempdir(), json_filename)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        # Send JSON
        await client.send_document(
            chat_id=user_id,
            document=json_path,
            caption=(
                f"✅ **Conversion complete!**\n"
                f"📊 {total_q} questions extracted.\n"
                f"📁 {json_filename}"
            ),
            file_name=json_filename,
            parse_mode=ParseMode.HTML
        )

        # Send a summary TXT as backup (optional)
        txt_content = f"PDF: {doc.file_name}\nQuestions: {total_q}\nDate: {datetime.now()}\n\nFirst 3 questions:\n"
        for q in output["questions"][:3]:
            txt_content += f"{q['questionNumber']}. {q['question'][:100]}...\n"
        txt_path = json_path.replace(".json", "_summary.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(txt_content)
        await client.send_document(
            chat_id=user_id,
            document=txt_path,
            caption="📋 Summary report",
            file_name=f"{doc.file_name.replace('.pdf', '')}_summary.txt",
            parse_mode=ParseMode.HTML
        )

        # Save to MongoDB if available
        if conversions_collection is not None:
            conversions_collection.insert_one({
                "user_id": user_id,
                "pdf_name": doc.file_name,
                "total_questions": total_q,
                "timestamp": datetime.now()
            })

        await status_msg.delete()
        del active_conversions[user_id]
        del user_sessions[user_id]

    except Exception as e:
        logger.error(traceback.format_exc())
        await status_msg.edit_text(
            f"❌ **Error:** {str(e)[:200]}\n\n"
            "Check the PDF or try again.",
            parse_mode=ParseMode.HTML
        )
        # Send error log
        error_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
        error_file.write(traceback.format_exc().encode())
        error_file.close()
        await client.send_document(
            chat_id=user_id,
            document=error_file.name,
            caption="🐛 Error log",
            file_name=f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            parse_mode=ParseMode.HTML
        )
        os.unlink(error_file.name)
        if user_id in active_conversions:
            del active_conversions[user_id]
        if user_id in user_sessions:
            del user_sessions[user_id]
    finally:
        for p in [temp_path, json_path]:
            if p and os.path.exists(p):
                os.unlink(p)

async def update_progress(status_msg, user_id, step, total, msg):
    """Callback to update progress message."""
    if user_id not in active_conversions:
        return
    progress = active_conversions[user_id]["progress"]
    elapsed = progress.get_elapsed_time()
    eta = calculate_eta(step, total, elapsed)
    pct = (step / total * 100) if total else 0
    bar = create_progress_bar(pct)
    text = (
        f"⏳ **Processing PDF**\n\n"
        f"**{msg}**\n"
        f"Progress: {pct:.1f}%\n{bar}\n"
        f"Pages: {step}/{total}\n"
        f"⏱️ Elapsed: {format_time(elapsed)}\n"
        f"⏱️ ETA: {eta}"
    )
    try:
        await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

# ---------- Callbacks ----------
@app.on_callback_query()
async def callback_handler(client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    if data == "start_convert":
        await pdf2json_cmd(client, callback_query.message)
    elif data == "cancel":
        if user_id in user_sessions:
            del user_sessions[user_id]
        await callback_query.message.reply_text("❌ Cancelled.", parse_mode=ParseMode.HTML)
    await callback_query.answer()

# ---------- Run ----------
if __name__ == "__main__":
    print("🤖 Starting PDF Converter Bot...")
    app.run()
