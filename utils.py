import logging
import time
from datetime import datetime

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    return logger

class ProgressTracker:
    def __init__(self):
        self.start_time = None
    def start(self):
        self.start_time = time.time()
    def get_elapsed_time(self):
        if not self.start_time:
            return 0
        return time.time() - self.start_time

def format_file_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"

def calculate_eta(current, total, elapsed):
    if current == 0 or elapsed == 0:
        return "Calculating..."
    speed = current / elapsed
    remaining = total - current
    eta = remaining / speed if speed > 0 else 0
    return format_time(eta)

def create_progress_bar(percentage, length=20):
    filled = int((percentage / 100) * length)
    return "█" * filled + "░" * (length - filled)
