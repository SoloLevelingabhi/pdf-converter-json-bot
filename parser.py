import pdfplumber
import re
import json
import logging
from typing import List, Dict, Optional
import asyncio

logger = logging.getLogger(__name__)

# ---------- Constants from your scripts ----------
NOISE = {
    "Telegram", "Link", "Maths", "By", "gagan", "Pratap", "Sir",
    "Static", "GK", "(total", "Q", "-", "185)", "otat", "otal",
    "IN", "Selection", "Way", "TG", "y", "Application", "You",
}
EXAM_KEYWORDS = {"DP", "SSC", "MTS", "CPO", "CGL", "CHSL", "Steno",
                 "Phase", "AWO", "TPO", "HC", "Tier-1", "Shift"}
Q_MARKER_RE = re.compile(r"^(\d{4})\)\s")
S_MARKER_RE = re.compile(r"^Q(\d{4})\.")
OPT_RE = re.compile(r"\(([A-D])\)\s*")
ANS_RE = re.compile(r"Ans:\s*\(([A-D])\)")

def is_noise(word):
    return word["text"] in NOISE

def group_lines(ws, threshold=3.0):
    if not ws:
        return []
    ws = sorted(ws, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines = []
    cur = []
    cur_top = None
    for w in ws:
        if cur_top is None or abs(w["top"] - cur_top) <= threshold:
            cur.append(w)
            cur_top = w["top"] if cur_top is None else cur_top
        else:
            lines.append(cur)
            cur = [w]
            cur_top = w["top"]
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        ln = sorted(ln, key=lambda w: w["x0"])
        out.append(" ".join(w["text"] for w in ln))
    return out

def parse_question_text(num, lines):
    """Parse a question block into fields (same logic as parse_questions.py)."""
    first = lines[0]
    m = Q_MARKER_RE.match(first)
    qtext_start = first[m.end():] if m else first
    body_lines = [qtext_start] + lines[1:]
    joined = "\n".join(body_lines)

    # Extract exam name
    exam_name = ""
    tokens = joined.split()
    i = 0
    keep = []
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("("):
            depth = 0
            run = []
            run_end = i
            for j in range(i, len(tokens)):
                run.append(tokens[j])
                for ch in tokens[j]:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                if depth <= 0:
                    run_end = j + 1
                    break
            if run_end > i:
                text = " ".join(run)
                if re.search(r"Shift\s+\d+\)$", text) and any(kw in text for kw in EXAM_KEYWORDS):
                    inner = text[1:].rstrip(")").strip()
                    if not exam_name:
                        exam_name = inner
                    i = run_end
                    continue
        keep.append(tok)
        i += 1
    joined = " ".join(keep)
    joined = re.sub(r"\s+", " ", joined).strip()

    ans_match = ANS_RE.search(joined)
    correct_answer = ans_match.group(1) if ans_match else ""
    joined_no_ans = ANS_RE.sub("", joined)

    # Replace Assertion (A) markers with (X) to avoid confusion
    work = re.sub(r"(?<=Assertion )\([A-D]\)", "(X)", joined_no_ans)

    positions = []
    for om in OPT_RE.finditer(work):
        positions.append((om.group(1), om.start(), om.end()))
    options = {"A": "", "B": "", "C": "", "D": ""}
    for i, (letter, s, e) in enumerate(positions):
        end = positions[i+1][1] if i+1 < len(positions) else len(joined_no_ans)
        opt_text = joined_no_ans[e:end].strip()
        opt_text = re.sub(r"\s+", " ", opt_text).strip()
        options[letter] = opt_text
    if positions:
        qtext = joined_no_ans[:positions[0][1]].strip()
    else:
        qtext = joined_no_ans.strip()
    qtext = re.sub(r"\s+", " ", qtext).strip()

    correct_option_text = options.get(correct_answer, "")

    return {
        "questionNumber": num,
        "question": qtext,
        "optionA": options["A"],
        "optionB": options["B"],
        "optionC": options["C"],
        "optionD": options["D"],
        "correctAnswer": correct_answer,
        "correctOptionText": correct_option_text,
        "examName": exam_name,
        "solution": "",  # will be filled later
        "subtopic": "",
        "hint": "",
        "difficulty": "Medium",
        "questionData": {},
        "questionFormat": "MCQ",
        "status": "ACTIVE",
        "version": 1
    }

async def enrich_with_ai(question_data: Dict, api_key: str) -> Dict:
    """Optional AI enrichment using agentrouter.org GLM-5.2."""
    # Placeholder: you can implement the actual API call here
    # For now, we return as-is
    return question_data

async def parse_pdf(pdf_path: str, progress_callback=None) -> Dict:
    """
    Main parsing function. Returns dict with 'questions' list.
    progress_callback(step, total, message)
    """
    logger.info(f"Parsing PDF: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        page_width = pdf.pages[0].width
        mid = page_width / 2.0

        all_lines = []
        total_pages = len(pdf.pages)

        for pno, page in enumerate(pdf.pages, start=1):
            words = [w for w in page.extract_words() if not is_noise(w)]
            left = [w for w in words if w["x0"] < mid]
            right = [w for w in words if w["x0"] >= mid]
            all_lines.extend(group_lines(left))
            all_lines.extend(group_lines(right))

            if progress_callback:
                await progress_callback(pno, total_pages, f"Extracting page {pno}/{total_pages}")

    # Split into questions and solutions
    questions = {}
    solutions = {}
    current = None
    for ln in all_lines:
        qm = Q_MARKER_RE.match(ln)
        sm = S_MARKER_RE.match(ln)
        if qm:
            num = int(qm.group(1))
            current = ("Q", num)
            questions.setdefault(num, []).append(ln)
        elif sm:
            num = int(sm.group(1))
            current = ("S", num)
            solutions.setdefault(num, []).append(ln)
        else:
            if current is None:
                continue
            kind, num = current
            if kind == "Q":
                questions.setdefault(num, []).append(ln)
            else:
                solutions.setdefault(num, []).append(ln)

    # Build final question objects
    result_questions = []
    for num in sorted(questions.keys()):
        qdata = parse_question_text(num, questions[num])
        sol_text = "\n".join(solutions.get(num, []))
        qdata["solution"] = sol_text

        # Optional AI enrichment
        if Config.ENABLE_AI and Config.AI_API_KEY:
            qdata = await enrich_with_ai(qdata, Config.AI_API_KEY)

        result_questions.append(qdata)

    return {"questions": result_questions}
