# Telegram Expense Tracker Bot

A simple telegram bot to track expenses for personal use. Entries are logged to SQLite locally and synced to Google Sheets automatically.

---

## Quick Setup

### 1. Create your Telegram bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot` → follow prompts → copy the **BOT_TOKEN**
3. Optionally send `/setcommands` to BotFather and paste:
   ```
   start - Welcome message
   add - Log an expense
   categories - Pick category with buttons
   edit - Edit a recent entry
   summary - Monthly breakdown
   history - Recent expenses
   delete - Remove an entry
   help - Show help
   ```

### 2. Find your Telegram User ID

Open @userinfobot on Telegram — it tells you your numeric user ID.
Set it as `ALLOWED_USER_ID` so only you can use the bot.

### 3. Set up Google Sheets sync

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to **IAM & Admin** and create a **Service Account** 
5. Create a JSON key (JSON) → download → save as `credentials.json` in this folder
6. Create a new [Google Sheet](https://sheets.google.com)
7. Share the sheet with the service account email (from `credentials.json` → `client_email`) as **Editor**
8. Copy the Spreadsheet ID from the URL

### 4. Configure environment

.env
```
BOT_TOKEN=your_telegram_bot_token
ALLOWED_USER_ID=your_telegram_user_id
WEBHOOK_URL=https://your-app.onrender.com
PORT=8443
SPREADSHEET_ID=your_google_spreadsheet_id
GOOGLE_CREDENTIALS=credentials.json
```

### 5. Install dependencies
`pip install -r requirements.txt`

### 6. Hosting

1. Push this repo to GitHub and connect it on Render (New Web Service)
2. Set Start command: `python bot.py`
3. Add all environment variables from your .env under Environment
4. Upload credentials.json as a Secret File at path credentials.json
5. Set https://your-app.onrender.com provided by Render as WEBHOOK_URL

---

## 🗂 Project structure

```
expense_bot/
├── bot.py           # Main bot logic + command handlers
├── db.py      # SQLite layer
├── sheets.py        # Google Sheets sync
├── requirements.txt
├── .env
└── .gitignore
├── credentials.json # (not committed to git)
└── expenses.db      # (auto-created on first run)
```
---