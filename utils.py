# utils.py
import logging
import time
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import json
import hashlib

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
                    logger.info(f"✅ Extracted page {page_num}/{total_pages}")
                else:
                    logger.warning(f"⚠️ No text on page {page_num}")
            except Exception as e:
                logger.error(f"Page {page_num} extraction error: {e}")
                continue
                
        return text
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        return ""

def process_questions(text: str, pdf_name: str) -> Dict:
    """Process questions with enhanced extraction"""
    lines = text.split('\n')
    questions = []
    question_count = 0
    
    # Patterns for extraction
    question_pattern = re.compile(r'^(\d+)\.?\s+(.*)')
    option_pattern = re.compile(r'^([A-D])\.?\s+(.*)')
    answer_pattern = re.compile(r'^(?:Answer|Ans|Correct Answer|Correct Option)\s*[:.]?\s*([A-D])', re.IGNORECASE)
    solution_pattern = re.compile(r'^(?:Solution|Sol|Explanation)\s*[:.]?\s*(.*)', re.IGNORECASE)
    exam_pattern = re.compile(r'^(?:Exam|SSC|UPSC|Bank|Railway)\s*(.*)', re.IGNORECASE)
    
    current_question = None
    current_solution = []
    collecting_solution = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if it's a question number
        q_match = question_pattern.match(line)
        if q_match:
            # Save previous question
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
            
        # Check for options
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
                
        # Check for answer
        elif current_question and answer_pattern.match(line):
            ans_match = answer_pattern.match(line)
            current_question["correctAnswer"] = ans_match.group(1)
            # Try to find the option text
            if current_question["correctAnswer"] == 'A':
                current_question["correctOptionText"] = current_question.get("optionA", "")
            elif current_question["correctAnswer"] == 'B':
                current_question["correctOptionText"] = current_question.get("optionB", "")
            elif current_question["correctAnswer"] == 'C':
                current_question["correctOptionText"] = current_question.get("optionC", "")
            elif current_question["correctAnswer"] == 'D':
                current_question["correctOptionText"] = current_question.get("optionD", "")
                
        # Check for solution
        elif current_question and solution_pattern.match(line):
            sol_match = solution_pattern.match(line)
            current_solution = [sol_match.group(1)]
            collecting_solution = True
            
        # Collect solution lines
        elif current_question and collecting_solution:
            if line:
                current_solution.append(line)
            else:
                collecting_solution = False
                
        # Check for exam name
        elif current_question and exam_pattern.match(line):
            exam_match = exam_pattern.match(line)
            current_question["examName"] = exam_match.group(1)
    
    # Add the last question
    if current_question:
        if current_solution:
            current_question["solution"] = " ".join(current_solution)
        questions.append(current_question)
        question_count += 1
    
    # Create final JSON
    output_json = {
        "schemaVersion": "1.0",
        "pdfName": pdf_name,
        "topic": "Static GK",
        "topicCode": "SGK",
        "totalQuestions": len(questions),
        "questions": questions
    }
    
    return output_json

def validate_json_output(data: Dict, expected_count: int) -> Dict:
    """Validate JSON output"""
    warnings = []
    valid = True
    
    # Check required fields
    required_fields = ["schemaVersion", "pdfName", "topic", "topicCode", "totalQuestions", "questions"]
    for field in required_fields:
        if field not in data:
            warnings.append(f"Missing field: {field}")
            valid = False
    
    # Check question count
    actual_count = len(data.get("questions", []))
    if actual_count != expected_count:
        warnings.append(f"Question count mismatch: expected {expected_count}, got {actual_count}")
        valid = False
    
    # Check each question
    for i, q in enumerate(data.get("questions", [])):
        required_q_fields = ["questionId", "questionNumber", "questionFormat", "question"]
        for field in required_q_fields:
            if field not in q:
                warnings.append(f"Question {i+1} missing field: {field}")
                valid = False
        
        # Check questionId format
        qid = q.get("questionId", "")
        if not qid.startswith("QID-SGK-2025-"):
            warnings.append(f"Invalid questionId format: {qid}")
            valid = False
    
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

# Initialize logger
logger = setup_logging()
