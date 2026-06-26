
# PDF to JSON Converter Bot

A powerful Telegram bot that converts SSC exam PDFs to structured JSON format using Google Gemini AI for intelligent extraction.

## Features

- AI-powered extraction using Google Gemini 1.5 Flash
- Real-time progress tracking with ETA
- Intelligent question detection and formatting
- Preserves original wording and structure
- Supports scanned PDFs (via AI vision)
- Automatic subtopic and difficulty classification
- MongoDB integration for analytics
- Docker and Heroku ready

## Output Format

```json
{
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
      "question": "Question text here...",
      "questionData": {},
      "optionA": "Option A text",
      "optionB": "Option B text",
      "optionC": "Option C text",
      "optionD": "Option D text",
      "correctAnswer": "A",
      "correctOptionText": "Option A text",
      "examName": "SSC CGL",
      "solution": "Explanation...",
      "subtopic": "History",
      "hint": "",
      "difficulty": "Medium",
      "status": "ACTIVE",
      "version": 1
    }
  ]
}
```

## Heroku Deployment (Recommended)

### Prerequisites

1. Get Telegram Bot Token from [@BotFather](https://t.me/BotFather)
2. Get Telegram API ID and Hash from [my.telegram.org](https://my.telegram.org)
3. Get Gemini API Key from [Google AI Studio](https://aistudio.google.com/app/apikey)
4. Get your Telegram User ID from [@userinfobot](https://t.me/userinfobot)

### Steps

1. Fork this repository or create new repo with these files

2. Create new Heroku app:
   - Go to [Heroku Dashboard](https://dashboard.heroku.com)
   - Click "New" → "Create new app"
   - Choose a name and region

3. Connect GitHub:
   - Go to "Deploy" tab
   - Select "GitHub" as deployment method
   - Connect your repository

4. Set Environment Variables (Settings → Config Vars):
   ```
   API_ID=your_api_id
   API_HASH=your_api_hash
   BOT_TOKEN=your_bot_token
   GEMINI_API_KEY=your_gemini_api_key
   OWNER_ID=your_telegram_id
   DATABASE_NAME=pdf_converter
   ```

5. Add Buildpacks (Settings → Buildpacks):
   ```
   https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git
   https://github.com/sunny4381/heroku-buildpack-poppler.git
   heroku/python
   ```

6. Deploy:
   - Go to "Deploy" tab
   - Click "Deploy Branch" (or enable Automatic Deploys)

7. Start Worker:
   - Go to "Resources" tab
   - Enable the worker dyno

## Local Development

1. Install dependencies:
   ```bash
   # On Ubuntu/Debian
   sudo apt-get install poppler-utils

   # On macOS
   brew install poppler
   ```

2. Clone and setup:
   ```bash
   git clone https://github.com/yourusername/pdf-converter-bot.git
   cd pdf-converter-bot
   pip install -r requirements.txt
   ```

3. Create `.env` file:
   ```
   API_ID=your_api_id
   API_HASH=your_api_hash
   BOT_TOKEN=your_bot_token
   GEMINI_API_KEY=your_gemini_api_key
   OWNER_ID=your_telegram_id
   DATABASE_NAME=pdf_converter
   ```

4. Run:
   ```bash
   python main.py
   ```

## Bot Commands

- `/start` - Start the bot and show welcome message
- `/pdf2json` - Start PDF conversion process
- `/status` - Check bot status and statistics
- `/progress` - View active conversion progress
- `/help` - Show detailed help
- `/cancel` - Cancel ongoing conversion

## Project Structure

```
pdf-converter-bot/
├── main.py           # Main bot logic
├── config.py         # Configuration settings
├── utils.py          # Gemini AI extraction logic
├── requirements.txt  # Python dependencies
├── Dockerfile         # Docker configuration
├── docker-compose.yml # Docker Compose setup
├── app.json          # Heroku app configuration
├── Procfile          # Heroku worker process
├── runtime.txt       # Python version
├── .env.example      # Environment variables template
├── .gitignore
└── README.md
```

## Notes

- Maximum PDF file size: 50MB
- Works with both text-based and scanned PDFs
- Gemini API free tier: 1500 requests/day
- If Gemini extraction fails, falls back to regex extraction

