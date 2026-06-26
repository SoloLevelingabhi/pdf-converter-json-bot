# main.py
import asyncio
import os
import tempfile
import json
import re
import logging
import traceback
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, RPCError
from PyPDF2 import PdfReader
import pymongo
from dotenv import load_dotenv

load_dotenv()

from config import Config
from utils import (
    setup_logging,
    ProgressTracker,
    extract_pdf_text,
    process_questions,
    validate_json_output,
    format_file_size,
    calculate_eta
)

# Setup logging
logger = setup_logging()

# Initialize MongoDB
try:
    mongo_client = pymongo.MongoClient(Config.MONGO_URI)
    db = mongo_client[Config.DATABASE_NAME]
    sessions_collection = db["user_sessions"]
    conversions_collection = db["conversions"]
    logger.info("✅ MongoDB connected successfully")
except Exception as e:
    logger.error(f"❌ MongoDB connection failed: {e}")
    sessions_collection = None
    conversions_collection = None

# Initialize bot
app = Client(
    "pdf_converter_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

# Store user sessions with progress tracking
user_sessions: Dict[int, Dict] = {}

# Store active conversions for real-time tracking
active_conversions: Dict[int, Dict] = {}

# Command handler for /start
@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    """Handle /start command with enhanced UI"""
    user = message.from_user
    welcome_text = """
🌟 <b>Welcome to PDF to JSON Converter Bot!</b>

Hello <b>{}</b>! 👋

I'm an advanced bot designed to convert SSC exam PDFs to structured JSON format with precision.

<b>✨ Features:</b>
• 📄 Extract questions from PDFs
• 🔍 Real-time progress tracking
• 📊 Automatic question numbering
• 🎯 Preserve original formatting
• 📈 Export to JSON format
• 🔄 Support for multiple question types

<b>📚 Commands:</b>
/start - Show this message
/pdf2json - Start conversion process
/status - Check current status
/progress - View active conversion progress
/help - Detailed help guide
/cancel - Cancel ongoing conversion

<b>🚀 Quick Start:</b>
1. Click /pdf2json
2. Upload your PDF file
3. Watch real-time progress
4. Get your JSON file!

<b>⚠️ Note:</b> Maximum file size: 50MB
    """.format(user.first_name)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Start Conversion", callback_data="start_convert")],
        [InlineKeyboardButton("📊 View Status", callback_data="view_status")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ])
    
    await message.reply_text(welcome_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

# Command handler for /help
@app.on_message(filters.command("help"))
async def help_command(client, message: Message):
    """Handle /help command with detailed information"""
    help_text = """
📚 <b>Comprehensive Help Guide</b>

<b>📌 What does this bot do?</b>
Converts SSC exam PDFs to structured JSON format with all questions, options, answers, and solutions.

<b>📄 Supported PDF Types:</b>
• SSC CGL, CHSL, MTS, CPO
• UPSC Prelims
• State PSC exams
• Any MCQ-based exam PDF

<b>🔍 Extraction Features:</b>
• Multiple question formats (MCQ, Assertion-Reason, Match the Following)
• Table extraction
• Image-based questions (metadata)
• Chronology questions
• Case studies

<b>📋 Output Format:</b>
• Schema version 1.0
• Unique question IDs
• Preserved formatting
• Original wording
• Complete solutions
• Difficulty assessment

<b>⚡ Performance Tips:</b>
• Use high-quality PDFs
• Ensure selectable text
• Avoid password-protected files
• Keep file size under 50MB

<b>❓ Common Issues:</b>
• <i>"Processing stuck"</i> → Wait or use /cancel
• <i>"No text extracted"</i> → PDF might be scanned
• <i>"JSON parsing error"</i> → Contact support

<b>🆘 Need Help?</b>
Contact: @support_username
    """
    await message.reply_text(help_text, parse_mode=ParseMode.HTML)

# Command handler for /pdf2json
@app.on_message(filters.command("pdf2json"))
async def pdf2json_command(client, message: Message):
    """Handle /pdf2json command with enhanced UI"""
    user_id = message.from_user.id
    
    # Check if user has active conversion
    if user_id in active_conversions:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Continue Previous", callback_data="continue_prev")],
            [InlineKeyboardButton("❌ Cancel Previous", callback_data="cancel_prev")],
            [InlineKeyboardButton("📤 New Upload", callback_data="upload_pdf")]
        ])
        await message.reply_text(
            "⚠️ <b>You have an active conversion!</b>\n\n"
            "Would you like to continue or start a new one?",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        return
    
    # Create inline keyboard
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Upload PDF", callback_data="upload_pdf")],
        [InlineKeyboardButton("📋 View Sample Output", callback_data="sample_output")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    
    await message.reply_text(
        "📄 <b>PDF to JSON Converter</b>\n\n"
        "Please upload the PDF file you want to convert.\n\n"
        "<b>📋 Requirements:</b>\n"
        "• Format: PDF\n"
        "• Max size: 50MB\n"
        "• Must contain SSC exam questions\n"
        "• Clear numbering (1., 2., etc.)\n"
        "• Text must be selectable\n\n"
        "Press the button below to upload or send the file directly.",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    
    # Set user session state
    user_sessions[user_id] = {
        "state": "waiting_for_pdf",
        "timestamp": datetime.now(),
        "attempts": 0
    }
    
    # Save session to MongoDB if available
    if sessions_collection is not None:
        try:
            sessions_collection.update_one(
                {"user_id": user_id},
                {"$set": {
                    "state": "waiting_for_pdf",
                    "timestamp": datetime.now(),
                    "username": message.from_user.username,
                    "first_name": message.from_user.first_name
                }},
                upsert=True
            )
        except Exception as e:
            logger.error(f"MongoDB save error: {e}")

# Command handler for /status
@app.on_message(filters.command("status"))
async def status_command(client, message: Message):
    """Check bot status with detailed information"""
    active_sessions = len(user_sessions)
    active_convs = len(active_conversions)
    
    # Get system info
    total_memory = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / (1024.**3)
    try:
        import psutil
        cpu_percent = psutil.cpu_percent()
        memory_percent = psutil.virtual_memory().percent
        memory_used = psutil.virtual_memory().used / (1024.**3)
        memory_total = psutil.virtual_memory().total / (1024.**3)
    except:
        cpu_percent = "N/A"
        memory_percent = "N/A"
        memory_used = "N/A"
        memory_total = "N/A"
    
    status_text = f"""
🟢 <b>Bot Status</b>

<b>📊 Statistics:</b>
• Active sessions: <code>{active_sessions}</code>
• Active conversions: <code>{active_convs}</code>
• Total processed today: <code>{get_today_count()}</code>

<b>💻 System Info:</b>
• CPU Usage: <code>{cpu_percent}%</code>
• Memory Usage: <code>{memory_percent}%</code>
• Memory Used: <code>{memory_used:.2f} GB</code>
• Total Memory: <code>{memory_total:.2f} GB</code>
• Uptime: <code>{get_uptime()}</code>

<b>📈 Performance:</b>
• Average processing time: <code>{get_avg_processing_time()}</code>
• Success rate: <code>{get_success_rate()}</code>

Use /pdf2json to start a new conversion!
    """
    await message.reply_text(status_text, parse_mode=ParseMode.HTML)

# Command handler for /progress
@app.on_message(filters.command("progress"))
async def progress_command(client, message: Message):
    """Show real-time progress of active conversion"""
    user_id = message.from_user.id
    
    if user_id not in active_conversions:
        await message.reply_text(
            "❌ <b>No active conversion</b>\n\n"
            "You don't have any conversion in progress.\n"
            "Start one with /pdf2json",
            parse_mode=ParseMode.HTML
        )
        return
    
    progress_data = active_conversions[user_id]
    await send_progress_update(message, progress_data)

async def send_progress_update(message: Message, progress_data: Dict):
    """Send progress update to user"""
    current_step = progress_data.get("current_step", "Initializing...")
    pages_processed = progress_data.get("pages_processed", 0)
    total_pages = progress_data.get("total_pages", 0)
    questions_found = progress_data.get("questions_found", 0)
    start_time = progress_data.get("start_time", datetime.now())
    elapsed = (datetime.now() - start_time).total_seconds()
    
    # Calculate progress percentage
    if total_pages > 0:
        progress_percent = min((pages_processed / total_pages) * 100, 100)
    else:
        progress_percent = 0
    
    # Calculate ETA
    eta = calculate_eta(pages_processed, total_pages, elapsed)
    
    progress_text = f"""
📊 <b>Conversion Progress</b>

<b>Status:</b> <code>{current_step}</code>

<b>📊 Progress:</b> {progress_percent:.1f}%
[{create_progress_bar(progress_percent)}]

<b>📄 Pages:</b>
• Processed: <code>{pages_processed}</code>
• Total: <code>{total_pages}</code>
• Remaining: <code>{total_pages - pages_processed}</code>

<b>📝 Questions:</b>
• Found: <code>{questions_found}</code>

<b>⏱️ Time:</b>
• Elapsed: <code>{format_time(elapsed)}</code>
• ETA: <code>{eta}</code>
• Speed: <code>{calculate_speed(pages_processed, elapsed)}</code>

<b>📈 Last 10 pages:</b>
{get_recent_activity(progress_data)}
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_progress")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_conversion")]
    ])
    
    await message.reply_text(progress_text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

def create_progress_bar(percentage: float, length: int = 20) -> str:
    """Create a visual progress bar"""
    filled = int((percentage / 100) * length)
    bar = "█" * filled + "░" * (length - filled)
    return bar

def format_time(seconds: float) -> str:
    """Format time in a readable format"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

def calculate_speed(pages: int, elapsed: float) -> str:
    """Calculate processing speed"""
    if elapsed == 0:
        return "0 pages/sec"
    speed = pages / elapsed
    return f"{speed:.2f} pages/sec"

def get_recent_activity(progress_data: Dict) -> str:
    """Get recent activity log"""
    recent_logs = progress_data.get("recent_logs", [])[-10:]
    if not recent_logs:
        return "No recent activity"
    return "\n".join([f"• {log}" for log in recent_logs])

def get_today_count() -> int:
    """Get number of conversions today"""
    if conversions_collection is None:
        return 0
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return conversions_collection.count_documents({
            "timestamp": {"$gte": today_start}
        })
    except:
        return 0

def get_uptime() -> str:
    """Get bot uptime"""
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
            return format_time(uptime_seconds)
    except:
        return "N/A"

def get_avg_processing_time() -> str:
    """Get average processing time"""
    if conversions_collection is None:
        return "N/A"
    try:
        pipeline = [
            {"$match": {"processing_time": {"$exists": True}}},
            {"$group": {"_id": None, "avg_time": {"$avg": "$processing_time"}}}
        ]
        result = list(conversions_collection.aggregate(pipeline))
        if result:
            avg_seconds = result[0]["avg_time"]
            return format_time(avg_seconds)
        return "N/A"
    except:
        return "N/A"

def get_success_rate() -> str:
    """Get conversion success rate"""
    if conversions_collection is None:
        return "N/A"
    try:
        total = conversions_collection.count_documents({})
        successful = conversions_collection.count_documents({"status": "success"})
        if total == 0:
            return "N/A"
        rate = (successful / total) * 100
        return f"{rate:.1f}%"
    except:
        return "N/A"

# Callback query handler
@app.on_callback_query()
async def handle_callback(client, callback_query: CallbackQuery):
    """Handle all callback queries"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    try:
        if data == "upload_pdf":
            user_sessions[user_id] = {
                "state": "waiting_for_pdf",
                "timestamp": datetime.now(),
                "attempts": 0
            }
            await callback_query.message.reply_text(
                "📤 <b>Ready to receive PDF</b>\n\n"
                "Please send the PDF file now.\n"
                "You can either:\n"
                "• Upload as file\n"
                "• Forward a PDF file\n\n"
                "<i>Waiting for your PDF...</i>",
                parse_mode=ParseMode.HTML
            )
            
        elif data == "start_convert":
            await pdf2json_command(client, callback_query.message)
            
        elif data == "view_status":
            await status_command(client, callback_query.message)
            
        elif data == "help":
            await help_command(client, callback_query.message)
            
        elif data == "sample_output":
            sample = """{
  "schemaVersion": "1.0",
  "pdfName": "018 Static GK",
  "topic": "Static GK",
  "topicCode": "SGK",
  "totalQuestions": 185,
  "questions": [
    {
      "questionId": "QID-SGK-2025-000001",
      "questionNumber": 1,
      "questionFormat": "MCQ",
      "question": "Sample question text here...",
      "optionA": "Option A",
      "optionB": "Option B",
      "optionC": "Option C",
      "optionD": "Option D",
      "correctAnswer": "A",
      "solution": "Sample solution...",
      "subtopic": "Sample Topic",
      "difficulty": "Medium"
    }
  ]
}"""
            await callback_query.message.reply_text(
                f"📋 <b>Sample Output Format</b>\n\n"
                f"<code>{sample[:1000]}...</code>\n\n"
                f"Full output includes all 185 questions with complete details.",
                parse_mode=ParseMode.HTML
            )
            
        elif data == "continue_prev":
            if user_id in active_conversions:
                await send_progress_update(callback_query.message, active_conversions[user_id])
            else:
                await callback_query.message.reply_text("❌ No previous conversion found.")
                
        elif data == "cancel_prev":
            if user_id in active_conversions:
                active_conversions[user_id]["status"] = "cancelled"
                del active_conversions[user_id]
            await callback_query.message.reply_text("✅ Previous conversion cancelled.")
            
        elif data == "refresh_progress":
            if user_id in active_conversions:
                await send_progress_update(callback_query.message, active_conversions[user_id])
            else:
                await callback_query.message.reply_text("❌ No active conversion.")
                
        elif data == "cancel_conversion":
            if user_id in active_conversions:
                active_conversions[user_id]["status"] = "cancelled"
                del active_conversions[user_id]
            await callback_query.message.reply_text(
                "✅ <b>Conversion Cancelled</b>\n\n"
                "Your conversion has been stopped.\n"
                "Start a new one with /pdf2json",
                parse_mode=ParseMode.HTML
            )
            
        elif data == "cancel":
            if user_id in user_sessions:
                del user_sessions[user_id]
            await callback_query.message.reply_text(
                "❌ <b>Operation Cancelled</b>\n\n"
                "You can start again anytime with /pdf2json",
                parse_mode=ParseMode.HTML
            )
            
    except Exception as e:
        logger.error(f"Callback error: {traceback.format_exc()}")
        await callback_query.message.reply_text(f"⚠️ Error: {str(e)}")
    
    await callback_query.answer()

# Enhanced PDF handler with progress tracking
@app.on_message(filters.document & ~filters.command(["start", "help", "pdf2json", "status", "progress"]))
async def handle_pdf(client, message: Message):
    """Handle PDF file uploads with real-time progress"""
    user_id = message.from_user.id
    
    # Check if user is in the right session
    if user_id not in user_sessions or user_sessions[user_id].get("state") != "waiting_for_pdf":
        await message.reply_text(
            "⚠️ <b>Please start the process first!</b>\n\n"
            "Use /pdf2json command to begin the conversion.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if it's a PDF
    document = message.document
    if not document.file_name.lower().endswith('.pdf'):
        await message.reply_text(
            "❌ <b>Invalid file format</b>\n\n"
            "Please upload a PDF file only.\n"
            "Supported: .pdf\n\n"
            "Use /pdf2json to start again.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check file size (max 50MB)
    if document.file_size > 50 * 1024 * 1024:
        await message.reply_text(
            "❌ <b>File too large</b>\n\n"
            f"📦 Your file: {format_file_size(document.file_size)}\n"
            f"📦 Maximum allowed: 50MB\n\n"
            "Please compress the file or split it into smaller parts.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Initialize progress tracking
    progress = ProgressTracker()
    progress.start()
    
    # Store in active conversions
    active_conversions[user_id] = {
        "current_step": "Starting conversion...",
        "pages_processed": 0,
        "total_pages": 0,
        "questions_found": 0,
        "start_time": datetime.now(),
        "status": "processing",
        "recent_logs": [],
        "progress": progress
    }
    
    # Send processing message
    status_message = await message.reply_text(
        "⏳ <b>Processing your PDF...</b>\n\n"
        f"📄 <b>File:</b> <code>{document.file_name}</code>\n"
        f"📦 <b>Size:</b> <code>{format_file_size(document.file_size)}</code>\n\n"
        "🔄 <b>Status:</b> <code>Initializing...</code>\n"
        "📊 <b>Progress:</b> 0%\n"
        "⏱️ <b>ETA:</b> Calculating...\n\n"
        "<i>Please wait while I process your file...</i>",
        parse_mode=ParseMode.HTML
    )
    
    temp_path = None
    json_path = None
    
    try:
        # Download the PDF
        active_conversions[user_id]["current_step"] = "Downloading PDF..."
        active_conversions[user_id]["recent_logs"].append("📥 Downloading file...")
        
        await status_message.edit_text(
            update_progress_message(document.file_name, "Downloading PDF...", 0, 0, 0),
            parse_mode=ParseMode.HTML
        )
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_path = temp_file.name
            await client.download_media(message, file_name=temp_path)
        
        # Get total pages
        reader = PdfReader(temp_path)
        total_pages = len(reader.pages)
        active_conversions[user_id]["total_pages"] = total_pages
        
        active_conversions[user_id]["recent_logs"].append(f"📄 Found {total_pages} pages")
        
        # Extract text with progress
        active_conversions[user_id]["current_step"] = "Extracting text..."
        extracted_text = ""
        
        for page_num, page in enumerate(reader.pages, 1):
            try:
                # Update progress
                progress_percent = (page_num / total_pages) * 50  # First 50% for extraction
                active_conversions[user_id]["pages_processed"] = page_num
                
                # Update status message every 5 pages
                if page_num % 5 == 0:
                    elapsed = progress.get_elapsed_time()
                    eta = progress.calculate_eta(page_num, total_pages)
                    
                    await status_message.edit_text(
                        update_progress_message(
                            document.file_name,
                            f"Extracting page {page_num}/{total_pages}",
                            progress_percent,
                            elapsed,
                            eta,
                            page_num,
                            total_pages
                        ),
                        parse_mode=ParseMode.HTML
                    )
                
                page_text = page.extract_text()
                if page_text:
                    extracted_text += page_text + "\n"
                    
                active_conversions[user_id]["recent_logs"].append(f"✅ Page {page_num} extracted")
                
                # Add small delay to prevent flooding
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Page {page_num} extraction error: {e}")
                active_conversions[user_id]["recent_logs"].append(f"⚠️ Page {page_num} error: {str(e)[:50]}")
                continue
        
        if not extracted_text.strip():
            raise ValueError("No text could be extracted from the PDF. It might be a scanned document.")
        
        active_conversions[user_id]["current_step"] = "Processing questions..."
        active_conversions[user_id]["recent_logs"].append("🧠 Processing questions...")
        
        # Process the extracted text
        progress_percent = 51
        await status_message.edit_text(
            update_progress_message(
                document.file_name,
                "Processing questions with AI...",
                progress_percent,
                progress.get_elapsed_time(),
                "Processing...",
                total_pages,
                total_pages
            ),
            parse_mode=ParseMode.HTML
        )
        
        # Process questions with status updates
        result_json = process_questions(extracted_text, document.file_name.replace('.pdf', ''))
        
        # Update question count
        questions_count = len(result_json.get("questions", []))
        active_conversions[user_id]["questions_found"] = questions_count
        
        active_conversions[user_id]["recent_logs"].append(f"📊 Found {questions_count} questions")
        
        # Validate JSON
        progress_percent = 90
        await status_message.edit_text(
            update_progress_message(
                document.file_name,
                "Validating output...",
                progress_percent,
                progress.get_elapsed_time(),
                "Almost done...",
                total_pages,
                total_pages
            ),
            parse_mode=ParseMode.HTML
        )
        
        validation = validate_json_output(result_json, questions_count)
        if not validation["valid"]:
            logger.warning(f"Validation warnings: {validation['warnings']}")
            active_conversions[user_id]["recent_logs"].append(f"⚠️ Validation warnings: {len(validation['warnings'])}")
        
        # Create JSON file
        json_filename = f"{document.file_name.replace('.pdf', '').replace(' ', '_')}_{questions_count}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        json_path = os.path.join(tempfile.gettempdir(), json_filename)
        
        active_conversions[user_id]["current_step"] = "Saving output..."
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result_json, f, indent=2, ensure_ascii=False)
        
        # Send the JSON file
        progress_percent = 100
        processing_time = progress.get_elapsed_time()
        
        await status_message.edit_text(
            f"✅ <b>Processing Complete!</b>\n\n"
            f"📄 <b>File:</b> <code>{document.file_name}</code>\n"
            f"📊 <b>Questions Found:</b> <code>{questions_count}</code>\n"
            f"⏱️ <b>Time Taken:</b> <code>{format_time(processing_time)}</code>\n"
            f"📏 <b>Output Size:</b> <code>{format_file_size(os.path.getsize(json_path))}</code>\n\n"
            "📤 <b>Sending the JSON file...</b>",
            parse_mode=ParseMode.HTML
        )
        
        # Send JSON file
        await client.send_document(
            chat_id=user_id,
            document=json_path,
            caption=(
                f"✅ <b>PDF Converted Successfully!</b>\n\n"
                f"📄 <b>Original File:</b> <code>{document.file_name}</code>\n"
                f"📊 <b>Questions Extracted:</b> <code>{questions_count}</code>\n"
                f"📝 <b>Topic:</b> Static GK\n"
                f"🔖 <b>Code:</b> SGK\n"
                f"⏱️ <b>Processing Time:</b> <code>{format_time(processing_time)}</code>\n\n"
                f"📁 <b>Output File:</b>\n"
                f"<code>{json_filename}</code>\n\n"
                f"<b>⚠️ Important:</b> This is an automated extraction. "
                f"Please verify the data accuracy.\n\n"
                f"🔍 <b>Stats:</b>\n"
                f"• Success Rate: {get_success_rate()}\n"
                f"• Avg Time: {get_avg_processing_time()}"
            ),
            file_name=json_filename,
            parse_mode=ParseMode.HTML
        )
        
        # Send summary as text file for backup
        txt_content = (
            f"PDF CONVERSION REPORT\n"
            f"{'='*50}\n\n"
            f"PDF Name: {document.file_name}\n"
            f"Total Questions: {questions_count}\n"
            f"Processing Time: {format_time(processing_time)}\n"
            f"Output File: {json_filename}\n"
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Detailed Statistics:\n"
            f"{'-'*30}\n"
            f"Question Formats Found: {get_question_formats(result_json)}\n"
            f"Pages Processed: {total_pages}\n"
            f"Validation Status: {'PASSED' if validation['valid'] else 'WARNINGS'}\n"
            f"Validation Warnings: {len(validation['warnings'])}\n\n"
            f"First 5 Questions Preview:\n"
            f"{'-'*30}\n"
        )
        
        # Add first 5 questions preview
        for i, q in enumerate(result_json.get("questions", [])[:5], 1):
            txt_content += f"\n{i}. {q.get('question', '')[:100]}...\n"
            txt_content += f"   Answer: {q.get('correctAnswer', 'N/A')}\n"
            txt_content += f"   Subtopic: {q.get('subtopic', 'N/A')}\n"
            txt_content += f"   Difficulty: {q.get('difficulty', 'N/A')}\n"
        
        txt_path = json_path.replace('.json', '_report.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(txt_content)
        
        await client.send_document(
            chat_id=user_id,
            document=txt_path,
            caption="📋 <b>Conversion Report</b>\n\nDetailed report with statistics.",
            file_name=f"{document.file_name.replace('.pdf', '')}_report.txt",
            parse_mode=ParseMode.HTML
        )
        
        # Save to MongoDB if available
        if conversions_collection is not None:
            try:
                conversions_collection.insert_one({
                    "user_id": user_id,
                    "username": message.from_user.username,
                    "pdf_name": document.file_name,
                    "total_questions": questions_count,
                    "pages_processed": total_pages,
                    "processing_time": processing_time,
                    "status": "success",
                    "timestamp": datetime.now(),
                    "file_size": document.file_size,
                    "output_size": os.path.getsize(json_path)
                })
            except Exception as e:
                logger.error(f"MongoDB save error: {e}")
        
        # Clean up
        active_conversions[user_id]["status"] = "completed"
        del active_conversions[user_id]
        del user_sessions[user_id]
        
        await status_message.delete()
        
    except FloodWait as e:
        logger.warning(f"Flood wait: {e}")
        await status_message.edit_text(
            f"⏳ <b>Rate limited by Telegram</b>\n\n"
            f"Please wait {e.x} seconds before trying again.\n"
            f"This is a Telegram limitation, not a bot error.",
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(e.x)
        
    except Exception as e:
        logger.error(f"Processing error: {traceback.format_exc()}")
        
        # Get full error traceback
        error_traceback = traceback.format_exc()
        
        await status_message.edit_text(
            f"❌ <b>Error Processing PDF</b>\n\n"
            f"<b>Error:</b> <code>{str(e)[:200]}</code>\n\n"
            f"<b>Possible Solutions:</b>\n"
            f"• Ensure the PDF is not corrupted\n"
            f"• Make sure text is selectable\n"
            f"• Try a different PDF\n"
            f"• Check file size limits\n\n"
            f"<b>Full Error:</b>\n"
            f"<code>{error_traceback[:500]}...</code>\n\n"
            f"Please try again with /pdf2json",
            parse_mode=ParseMode.HTML
        )
        
        # Send error log as text file
        error_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
        error_file.write(f"ERROR LOG - {datetime.now()}\n{'='*50}\n\n{error_traceback}".encode())
        error_file.close()
        
        await client.send_document(
            chat_id=user_id,
            document=error_file.name,
            caption="🐛 <b>Error Log</b>\n\nPlease share this with support if the issue persists.",
            file_name=f"error_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            parse_mode=ParseMode.HTML
        )
        
        os.unlink(error_file.name)
        
        # Clean up
        if user_id in active_conversions:
            del active_conversions[user_id]
        if user_id in user_sessions:
            del user_sessions[user_id]
        
    finally:
        # Clean up temporary files
        try:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            if json_path and os.path.exists(json_path):
                os.unlink(json_path)
        except:
            pass

def update_progress_message(file_name, status, progress, elapsed, eta, current_page=0, total_pages=0):
    """Generate progress message"""
    bar = create_progress_bar(progress)
    
    if total_pages > 0:
        pages_info = f"📄 <b>Pages:</b> <code>{current_page}/{total_pages}</code>"
    else:
        pages_info = ""
    
    return f"""
⏳ <b>Processing your PDF...</b>

📄 <b>File:</b> <code>{file_name}</code>

<b>Status:</b> <code>{status}</code>
<b>Progress:</b> {progress:.1f}%
[{bar}]

{pages_info}
⏱️ <b>Elapsed:</b> <code>{format_time(elapsed)}</code>
⏱️ <b>ETA:</b> <code>{eta}</code>

<i>Please wait while I process your file...</i>
    """

def get_question_formats(result_json):
    """Get distribution of question formats"""
    formats = {}
    for q in result_json.get("questions", []):
        q_format = q.get("questionFormat", "MCQ")
        formats[q_format] = formats.get(q_format, 0) + 1
    return ", ".join([f"{k}: {v}" for k, v in formats.items()])

# Handler for forwarded PDFs
@app.on_message(filters.forwarded & filters.document)
async def handle_forwarded_pdf(client, message: Message):
    """Handle forwarded PDF files"""
    user_id = message.from_user.id
    
    # Check if it's a PDF
    document = message.document
    if not document.file_name.lower().endswith('.pdf'):
        await message.reply_text(
            "❌ <b>Invalid file format</b>\n\n"
            "Please forward a PDF file only.\n"
            "Use /pdf2json to start.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Reuse the handle_pdf logic
    await handle_pdf(client, message)

# Command handler for /cancel
@app.on_message(filters.command("cancel"))
async def cancel_command(client, message: Message):
    """Cancel ongoing operations"""
    user_id = message.from_user.id
    
    if user_id in active_conversions:
        active_conversions[user_id]["status"] = "cancelled"
        del active_conversions[user_id]
        await message.reply_text(
            "✅ <b>Conversion Cancelled</b>\n\nYour conversion has been stopped.",
            parse_mode=ParseMode.HTML
        )
    elif user_id in user_sessions:
        del user_sessions[user_id]
        await message.reply_text(
            "✅ <b>Operation Cancelled</b>\n\nYou can start again anytime.",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply_text(
            "❌ <b>No active operation</b>\n\nYou don't have any ongoing operation.",
            parse_mode=ParseMode.HTML
        )

# Error handler
@app.on_message()
async def handle_other_messages(client, message: Message):
    """Handle other messages"""
    user_id = message.from_user.id
    
    # Check if user is waiting for PDF but sent something else
    if user_id in user_sessions and user_sessions[user_id].get("state") == "waiting_for_pdf":
        await message.reply_text(
            "⚠️ <b>Please upload a PDF file</b>\n\n"
            "I need a PDF file to process.\n"
            "Use /pdf2json to start over.",
            parse_mode=ParseMode.HTML
        )
    else:
        # Ignore other messages
        pass

if __name__ == "__main__":
    print("🤖 Starting PDF to JSON Converter Bot...")
    print("📝 Version: 2.0.0")
    print("🐛 Debug Mode: Enabled")
    print("=" * 50)
    
    try:
        app.run()
    except Exception as e:
        logger.error(f"Fatal error: {traceback.format_exc()}")
        sys.exit(1)
