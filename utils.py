# utils.py
import logging
import time
import re
import base64
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable
from openai import OpenAI
from PIL import Image
import io
import os

from config import Config

def setup_logging():
    """Setup comprehensive logging"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler('bot.log')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    return logger

# Initialize logger
logger = setup_logging()

# Initialize AgentRouter OpenAI client
client = None
if Config.AGENTROUTER_API_KEY:
    client = OpenAI(
        api_key=Config.AGENTROUTER_API_KEY,
        base_url=Config.AGENTROUTER_BASE_URL
    )
    logger.info(f"AgentRouter API configured with model: {Config.VISION_MODEL}")
else:
    logger.warning("AGENTROUTER_API_KEY not set - extraction will use fallback regex method")

class ProgressTracker:
    """Track progress of conversion"""
    def __init__(self):
        self.start_time = None
        self.current_step = 0
        self.total_steps = 0
        self.logs = []

    def start(self):
        """Start tracking"""
        self.start_time = time.time()

    def update(self, step: int, total: int, message: str = ""):
        """Update progress"""
        self.current_step = step
        self.total_steps = total
        if message:
            self.logs.append(f"{datetime.now().strftime('%H:%M:%S')} - {message}")

    def get_progress(self) -> float:
        """Get progress percentage"""
        if self.total_steps == 0:
            return 0
        return (self.current_step / self.total_steps) * 100

    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds"""
        if not self.start_time:
            return 0
        return time.time() - self.start_time

    def calculate_eta(self, current: int, total: int) -> str:
        """Calculate ETA"""
        if current == 0 or not self.start_time:
            return "Calculating..."

        elapsed = self.get_elapsed_time()
        speed = current / elapsed if elapsed > 0 else 0
        remaining = total - current
        eta_seconds = remaining / speed if speed > 0 else 0

        return format_time(eta_seconds)

def pdf_to_images(pdf_path: str) -> List[bytes]:
    """Convert PDF pages to images"""
    try:
        from pdf2image import convert_from_path

        pages = convert_from_path(pdf_path, dpi=150)
        images = []

        for page in pages:
            img_byte_arr = io.BytesIO()
            page.save(img_byte_arr, format='PNG')
            images.append(img_byte_arr.getvalue())

        return images
    except Exception as e:
        logger.error(f"PDF to image conversion error: {e}")
        return []

def encode_image_to_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string"""
    return base64.b64encode(image_bytes).decode('utf-8')

def extract_with_agentrouter(pdf_path: str, pdf_name: str, progress_callback=None) -> Dict:
    """Extract questions from PDF using AgentRouter API with vision model"""

    if not client:
        logger.error("AgentRouter client not configured")
        return None

    try:
        # Convert PDF to images
        if progress_callback:
            progress_callback(5, "Converting PDF to images...")

        images = pdf_to_images(pdf_path)

        if not images:
            logger.error("Failed to convert PDF to images")
            return None

        total_pages = len(images)
        logger.info(f"Converted PDF to {total_pages} images")

        all_questions = []
        question_counter = 0

        # Process pages in batches for efficiency
        batch_size = 5

        for batch_start in range(0, total_pages, batch_size):
            batch_end = min(batch_start + batch_size, total_pages)
            batch_images = images[batch_start:batch_end]

            if progress_callback:
                progress_percent = 10 + int((batch_end / total_pages) * 70)
                progress_callback(progress_percent, f"Processing pages {batch_start+1}-{batch_end} with AgentRouter AI...")

            try:
                # Build messages with images
                content = []

                # Add text prompt
                prompt_text = f"""You are an expert at extracting questions from SSC exam PDFs.

Extract ALL questions from these {len(batch_images)} page(s). Return ONLY a valid JSON array:

[
  {{
    "questionNumber": 1,
    "question": "Full question text here",
    "optionA": "Option A text",
    "optionB": "Option B text",
    "optionC": "Option C text",
    "optionD": "Option D text",
    "correctAnswer": "A/B/C/D if shown",
    "solution": "Explanation if available",
    "examName": "Exam name like SSC CGL/CHSL/MTS if visible",
    "subtopic": "Subject/topic like History/Geography/Polity/Science",
    "difficulty": "Easy/Medium/Hard"
  }}
]

RULES:
1. Extract ALL questions from ALL pages in the images
2. Preserve exact wording and formatting
3. Include all 4 options (A, B, C, D)
4. If correct answer is visible, include it
5. If explanation/solution is visible, include it
6. Return ONLY the JSON array, no other text
7. No markdown formatting or backticks
8. Empty array [] if no questions found"""

                content.append({"type": "text", "text": prompt_text})

                # Add images
                for img_bytes in batch_images:
                    img_base64 = encode_image_to_base64(img_bytes)
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_base64}"
                        }
                    })

                # Call AgentRouter API
                response = client.chat.completions.create(
                    model=Config.VISION_MODEL,
                    messages=[{"role": "user", "content": content}],
                    max_tokens=4096,
                    temperature=0.1
                )

                # Clean response text
                response_text = response.choices[0].message.content.strip()

                # Remove potential markdown code blocks
                if response_text.startswith("```"):
                    response_text = re.sub(r'^```json?\s*', '', response_text)
                    response_text = re.sub(r'\s*```$', '', response_text)

                # Parse JSON
                try:
                    batch_questions = json.loads(response_text)

                    # Validate and format questions
                    for q in batch_questions:
                        question_counter += 1
                        formatted_q = {
                            "questionId": f"QID-SGK-2025-{str(question_counter).zfill(6)}",
                            "questionNumber": q.get("questionNumber", question_counter),
                            "questionFormat": "MCQ",
                            "question": q.get("question", ""),
                            "questionData": {},
                            "optionA": q.get("optionA", ""),
                            "optionB": q.get("optionB", ""),
                            "optionC": q.get("optionC", ""),
                            "optionD": q.get("optionD", ""),
                            "correctAnswer": q.get("correctAnswer", ""),
                            "correctOptionText": get_option_text(q.get("correctAnswer", ""), q),
                            "examName": q.get("examName", "SSC Exam"),
                            "solution": q.get("solution", ""),
                            "subtopic": q.get("subtopic", "General Knowledge"),
                            "hint": "",
                            "difficulty": q.get("difficulty", "Medium"),
                            "status": "ACTIVE",
                            "version": 1
                        }
                        all_questions.append(formatted_q)

                    logger.info(f"Batch {batch_start+1}-{batch_end}: Extracted {len(batch_questions)} questions")

                except json.JSONDecodeError as e:
                    logger.error(f"Batch JSON parse error: {e}")
                    logger.debug(f"Response was: {response_text[:500]}")
                    continue

            except Exception as e:
                logger.error(f"Batch processing error: {e}")
                continue

        if progress_callback:
            progress_callback(85, "Finalizing extraction...")

        # Create output JSON
        output = {
            "schemaVersion": "1.0",
            "pdfName": pdf_name,
            "topic": "Static GK",
            "topicCode": "SGK",
            "totalQuestions": len(all_questions),
            "questions": all_questions
        }

        return output

    except Exception as e:
        logger.error(f"AgentRouter extraction error: {e}")
        return None

def get_option_text(answer: str, question: Dict) -> str:
    """Get the text of the correct option"""
    if answer == 'A':
        return question.get("optionA", "")
    elif answer == 'B':
        return question.get("optionB", "")
    elif answer == 'C':
        return question.get("optionC", "")
    elif answer == 'D':
        return question.get("optionD", "")
    return ""

def process_questions_agentrouter(pdf_path: str, pdf_name: str, progress_callback=None) -> Dict:
    """Main function to process PDF with AgentRouter API"""

    if not client:
        logger.warning("AgentRouter not configured, using fallback regex extraction")
        return process_questions_regex(pdf_path, pdf_name, progress_callback)

    # Use AgentRouter extraction
    result = extract_with_agentrouter(pdf_path, pdf_name, progress_callback)

    if result and len(result.get("questions", [])) > 0:
        return result

    # Fallback to regex extraction
    logger.warning("AgentRouter extraction yielded no results, falling back to regex")
    return process_questions_regex(pdf_path, pdf_name, progress_callback)

def process_questions_regex(pdf_path: str, pdf_name: str, progress_callback=None) -> Dict:
    """Fallback regex-based extraction from PDF text"""
    from PyPDF2 import PdfReader

    if progress_callback:
        progress_callback(10, "Extracting text from PDF...")

    try:
        reader = PdfReader(pdf_path)
        text = ""
        total_pages = len(reader.pages)

        for page_num, page in enumerate(reader.pages, 1):
            try:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            except Exception as e:
                logger.error(f"Page {page_num} extraction error: {e}")
                continue

        if progress_callback:
            progress_callback(40, "Processing questions with regex...")

        lines = text.split('\n')
        questions = []
        question_count = 0

        question_pattern = re.compile(r'^(\d+)\.?\s+(.*)')
        option_pattern = re.compile(r'^([A-D])\.?\s+(.*)')
        answer_pattern = re.compile(r'^(?:Answer|Ans|Correct Answer|Correct Option)\s*[:.]?\s*([A-D])', re.IGNORECASE)
        solution_pattern = re.compile(r'^(?:Solution|Sol|Explanation)\s*[:.]?\s*(.*)', re.IGNORECASE)

        current_question = None
        current_solution = []
        collecting_solution = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            q_match = question_pattern.match(line)
            if q_match:
                if current_question:
                    if current_solution:
                        current_question["solution"] = " ".join(current_solution)
                        current_solution = []
                    questions.append(current_question)
                    question_count += 1

                q_num = int(q_match.group(1))
                q_text = q_match.group(2)

                current_question = {
                    "questionId": f"QID-SGK-2025-{str(question_count + 1).zfill(6)}",
                    "questionNumber": q_num,
                    "questionFormat": "MCQ",
                    "question": q_text,
                    "questionData": {},
                    "optionA": "",
                    "optionB": "",
                    "optionC": "",
                    "optionD": "",
                    "correctAnswer": "",
                    "correctOptionText": "",
                    "examName": "SSC Exam",
                    "solution": "",
                    "subtopic": "General Knowledge",
                    "hint": "",
                    "difficulty": "Medium",
                    "status": "ACTIVE",
                    "version": 1
                }
                collecting_solution = False

            elif current_question and option_pattern.match(line):
                opt_match = option_pattern.match(line)
                opt_letter = opt_match.group(1)
                opt_text = opt_match.group(2)

                if opt_letter == 'A':
                    current_question["optionA"] = opt_text
                elif opt_letter == 'B':
                    current_question["optionB"] = opt_text
                elif opt_letter == 'C':
                    current_question["optionC"] = opt_text
                elif opt_letter == 'D':
                    current_question["optionD"] = opt_text

            elif current_question and answer_pattern.match(line):
                ans_match = answer_pattern.match(line)
                current_question["correctAnswer"] = ans_match.group(1)
                current_question["correctOptionText"] = get_option_text(ans_match.group(1), current_question)

            elif current_question and solution_pattern.match(line):
                sol_match = solution_pattern.match(line)
                current_solution = [sol_match.group(1)]
                collecting_solution = True

            elif current_question and collecting_solution:
                if line:
                    current_solution.append(line)
                else:
                    collecting_solution = False

        if current_question:
            if current_solution:
                current_question["solution"] = " ".join(current_solution)
            questions.append(current_question)
            question_count += 1

        if progress_callback:
            progress_callback(90, "Finalizing extraction...")

        output = {
            "schemaVersion": "1.0",
            "pdfName": pdf_name,
            "topic": "Static GK",
            "topicCode": "SGK",
            "totalQuestions": len(questions),
            "questions": questions
        }

        return output

    except Exception as e:
        logger.error(f"Regex extraction error: {e}")
        return {
            "schemaVersion": "1.0",
            "pdfName": pdf_name,
            "topic": "Static GK",
            "topicCode": "SGK",
            "totalQuestions": 0,
            "questions": []
        }

# Keep old function names for compatibility
process_questions = process_questions_regex
process_questions_gemini = process_questions_agentrouter

def validate_json_output(data: Dict, expected_count: int) -> Dict:
    """Validate JSON output"""
    warnings = []
    valid = True

    required_fields = ["schemaVersion", "pdfName", "topic", "topicCode", "totalQuestions", "questions"]
    for field in required_fields:
        if field not in data:
            warnings.append(f"Missing field: {field}")
            valid = False

    actual_count = len(data.get("questions", []))
    if actual_count != expected_count:
        warnings.append(f"Question count mismatch: expected {expected_count}, got {actual_count}")

    for i, q in enumerate(data.get("questions", [])):
        required_q_fields = ["questionId", "questionNumber", "questionFormat", "question"]
        for field in required_q_fields:
            if field not in q:
                warnings.append(f"Question {i+1} missing field: {field}")

    return {"valid": valid, "warnings": warnings}

def format_file_size(size: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"

def format_time(seconds: float) -> str:
    """Format time in human readable format"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

def calculate_eta(current: int, total: int, elapsed: float) -> str:
    """Calculate ETA string"""
    if current == 0 or elapsed == 0:
        return "Calculating..."

    speed = current / elapsed
    remaining = total - current
    eta_seconds = remaining / speed if speed > 0 else 0

    return format_time(eta_seconds)

def get_file_hash(file_path: str) -> str:
    """Get MD5 hash of file"""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        buf = f.read(65536)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(65536)
    return hasher.hexdigest()

def extract_pdf_text(pdf_path: str) -> str:
    """Extract text from PDF with error handling"""
    from PyPDF2 import PdfReader

    try:
        reader = PdfReader(pdf_path)
        text = ""
        total_pages = len(reader.pages)

        for page_num, page in enumerate(reader.pages, 1):
            try:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            except Exception as e:
                logger.error(f"Page {page_num} extraction error: {e}")
                continue

        return text
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        return ""
