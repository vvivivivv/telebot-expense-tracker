"""
Requirements: pip install "python-telegram-bot[webhooks]" gspread google-auth
"""

import logging
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from db import Database
from sheets import SheetsClient

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation state (only for /categories flow)
AWAITING_AMOUNT = 0

BOT_TOKEN       = os.environ["BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))
WEBHOOK_URL     = os.environ["WEBHOOK_URL"]
PORT            = int(os.environ.get("PORT", "10000"))

db     = Database()
sheets = SheetsClient()

CATEGORIES = [
    "Food", "Transport", "Housing", "Health",
    "Entertainment", "Shopping", "Education", "Work", "Others"
]


def check_user(update: Update) -> bool:
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return
    await update.message.reply_text(
        "*Expense Tracker Bot*\n\n"
        "Commands:\n\n"
        "`/add <category> <amount> [note]` — Log an expense\n"
        "`/categories` — Show all categories\n"
        "`/edit` — Edit a recent entry\n"
        "`/summary` — This month's breakdown\n"
        "`/history [n]` — Last n expenses (default 10)\n"
        "`/delete <id>` — Remove an entry by ID\n"
        "`/help` — Show this message\n\n"
        "All expenses are synced to Google Sheets automatically",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ Usage: `/add <category> <amount> [note]`\n"
            "Or use /categories to pick via buttons.",
            parse_mode="Markdown"
        )
        return

    category_input = args[0].capitalize()
    matched_category = next(
        (c for c in CATEGORIES if category_input.lower() in c.lower()), None
    )
    if not matched_category:
        matched_category = category_input

    try:
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("Amount must be a number.", parse_mode="Markdown")
        return

    note = " ".join(args[2:]) if len(args) > 2 else ""
    expense_id = db.add_expense(matched_category, amount, note)
    sheets.append_expense(expense_id, matched_category, amount, note)

    now_str = datetime.now().strftime("%d %b %Y")
    await update.message.reply_text(
        f"*Logged!*\n\n"
        f"Date: {now_str}\n"
        f"Category: {matched_category}\n"
        f"Amount: ${amount:.2f}\n"
        f"Note: {note or '—'}\n"
        f"ID: `{expense_id}`\n"
        f"Synced to Google Sheets",
        parse_mode="Markdown"
    )


async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return

    keyboard = []
    row = []
    for i, cat in enumerate(CATEGORIES):
        row.append(InlineKeyboardButton(cat, callback_data=f"cat:{cat}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        "*Choose a category to log an expense:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("cat:", "")
    context.user_data["pending_category"] = category
    await query.edit_message_text(
        f"Category: *{category}*\n\nEnter the amount and optional note:\n`amount [note]`",
        parse_mode="Markdown"
    )
    return AWAITING_AMOUNT

async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return ConversationHandler.END

    parts = update.message.text.strip().split(maxsplit=1)
    try:
        amount = float(parts[0])
    except ValueError:
        await update.message.reply_text("Please enter a valid number.", parse_mode="Markdown")
        return AWAITING_AMOUNT

    note = parts[1] if len(parts) > 1 else ""
    category = context.user_data.get("pending_category", "Other")
    expense_id = db.add_expense(category, amount, note)
    sheets.append_expense(expense_id, category, amount, note)

    now_str = datetime.now().strftime("%d %b %Y")
    await update.message.reply_text(
        f"*Logged!*\n\n"
        f"Date: {now_str}\n"
        f"Category: {category}\n"
        f"Amount: ${amount:.2f}\n"
        f"Note: {note or '—'}\n"
        f"ID: `{expense_id}`\n"
        f"Synced to Google Sheets",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return

    expenses = db.get_recent(5)
    if not expenses:
        await update.message.reply_text("No expenses to edit yet.")
        return

    keyboard = []
    for eid, cat, amount, note, ts in expenses:
        date_str = datetime.fromisoformat(ts).strftime("%d %b")
        label = f"#{eid} {cat} ${amount:.2f} {date_str}"
        if note:
            label += f" — {note[:15]}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"editpick:{eid}")])

    await update.message.reply_text(
        "*Which entry do you want to edit?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def edit_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    eid = int(query.data.replace("editpick:", ""))

    expenses = db.get_recent(50)
    row = next((e for e in expenses if e[0] == eid), None)
    if not row:
        await query.edit_message_text("Entry not found.")
        return

    _, cat, amount, note, ts = row
    context.user_data["editing_id"]     = eid
    context.user_data["editing_cat"]    = cat
    context.user_data["editing_amount"] = amount
    context.user_data["editing_note"]   = note
    context.user_data["editing_ts"]     = ts

    keyboard = [
        [InlineKeyboardButton("Change date",     callback_data="editfield:date")],
        [InlineKeyboardButton("Change amount",   callback_data="editfield:amount")],
        [InlineKeyboardButton("Change note",     callback_data="editfield:note")],
        [InlineKeyboardButton("Change category", callback_data="editfield:category")],
    ]
    await query.edit_message_text(
        f"*Editing entry `#{eid}`*\n\n"
        f"Date: {datetime.fromisoformat(ts).strftime('%d %b %Y')}\n"
        f"Category: {cat}\n"
        f"Amount: ${amount:.2f}\n"
        f"Note: {note or '—'}\n\n"
        f"What do you want to change?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("editfield:", "")
    context.user_data["editing_field"] = field

    if field == "category":
        keyboard = []
        row = []
        for i, cat in enumerate(CATEGORIES):
            row.append(InlineKeyboardButton(cat, callback_data=f"editcat:{cat}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await query.edit_message_text(
            "*Pick the new category:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif field == "amount":
        await query.edit_message_text(
            f"*Current amount:* ${context.user_data['editing_amount']:.2f}\n\n"
            "Send the new amount:",
            parse_mode="Markdown"
        )

    elif field == "note":
        await query.edit_message_text(
            f"*Current note:* {context.user_data['editing_note'] or '—'}\n\n"
            "Send the new note (or `-` to clear it):",
            parse_mode="Markdown"
        )

    elif field == "date":
        current = datetime.fromisoformat(context.user_data["editing_ts"]).strftime("%d %b %Y")
        await query.edit_message_text(
            f"*Current date:* {current}\n\n"
            "Send the new date in format `DD-MM-YYYY` (e.g. `14-03-2026`):",
            parse_mode="Markdown"
        )

async def edit_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    new_cat = query.data.replace("editcat:", "")
    eid = context.user_data.get("editing_id")

    db.update_expense(eid, category=new_cat)
    sheets.update_expense_field(eid, category=new_cat)

    context.user_data.pop("editing_field", None)
    context.user_data.pop("editing_id",    None)

    await query.edit_message_text(
        f"*Category updated!*\n\nEntry `#{eid}` → {new_cat}\nSynced to Google Sheets",
        parse_mode="Markdown"
    )

async def handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles free-text replies for editing amount, note, or date."""
    field = context.user_data.get("editing_field")
    eid   = context.user_data.get("editing_id")
    if not field or not eid:
        return

    text = update.message.text.strip()

    if field == "amount":
        try:
            new_amount = float(text)
        except ValueError:
            await update.message.reply_text("Please enter a valid number (e.g. `6.50`).", parse_mode="Markdown")
            return
        db.update_expense(eid, amount=new_amount)
        sheets.update_expense_field(eid, amount=new_amount)
        await update.message.reply_text(
            f"*Amount updated!*\n\nEntry `#{eid}` → ${new_amount:.2f}\nSynced to Google Sheets",
            parse_mode="Markdown"
        )

    elif field == "note":
        new_note = "" if text == "-" else text
        db.update_expense(eid, note=new_note)
        sheets.update_expense_field(eid, note=new_note)
        await update.message.reply_text(
            f"*Note updated!*\n\nEntry `#{eid}` → {new_note or '—'}\nSynced to Google Sheets",
            parse_mode="Markdown"
        )

    elif field == "date":
        try:
            new_dt = datetime.strptime(text, "%d-%m-%Y")
            new_ts = new_dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            await update.message.reply_text(
                "Please use format `DD-MM-YYYY` (e.g. `14-03-2026`).",
                parse_mode="Markdown"
            )
            return
        db.update_expense(eid, created_at=new_ts)
        sheets.update_expense_field(eid, created_at=new_ts)
        await update.message.reply_text(
            f"*Date updated!*\n\nEntry `#{eid}` → {new_dt.strftime('%d %b %Y')}\nSynced to Google Sheets",
            parse_mode="Markdown"
        )

    context.user_data.pop("editing_field", None)
    context.user_data.pop("editing_id",    None)


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return

    now = datetime.now()
    data = db.monthly_summary(now.year, now.month)
    total = sum(v for _, v in data)

    if not data:
        await update.message.reply_text("No expenses logged this month yet.")
        return

    lines = [f"*{now.strftime('%B %Y')} Summary*\n"]
    for category, amount in sorted(data, key=lambda x: x[1], reverse=True):
        pct = (amount / total * 100) if total else 0
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        lines.append(f"{category}\n`{bar}` {pct:.0f}%  *${amount:.2f}*\n")

    lines.append(f"\n*Total: ${total:.2f}*")
    top = data[0][0] if data else "—"
    lines.append(f"Biggest category: {top}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return

    n = 10
    if context.args:
        try:
            n = int(context.args[0])
        except ValueError:
            pass

    expenses = db.get_recent(n)
    if not expenses:
        await update.message.reply_text("No expenses logged yet.")
        return

    lines = [f"*Last {len(expenses)} expenses:*\n"]
    for row in expenses:
        eid, cat, amount, note, ts = row
        date_str = datetime.fromisoformat(ts).strftime("%d %b %H:%M")
        lines.append(f"`#{eid}` {cat} — *${amount:.2f}* {note or ''}\n_{date_str}_\n")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def delete_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: `/delete <id>`", parse_mode="Markdown")
        return

    try:
        eid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID must be a number.")
        return

    success = db.delete_expense(eid)
    if success:
        sheets.delete_expense_row(eid)
        await update.message.reply_text(
            f"Expense `#{eid}` deleted.\nSynced to Google Sheets",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"Expense `#{eid}` not found.", parse_mode="Markdown")

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    cat_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(category_selected, pattern=r"^cat:")],
        states={AWAITING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start",      start))
    application.add_handler(CommandHandler("help",       help_cmd))
    application.add_handler(CommandHandler("add",        add_expense))
    application.add_handler(CommandHandler("categories", show_categories))
    application.add_handler(CommandHandler("summary",    summary))
    application.add_handler(CommandHandler("history",    history))
    application.add_handler(CommandHandler("delete",     delete_expense))
    application.add_handler(CommandHandler("edit",       edit))
    application.add_handler(CommandHandler("cancel",     cancel))
    application.add_handler(cat_conv_handler)

    application.add_handler(CallbackQueryHandler(edit_pick,              pattern=r"^editpick:"))
    application.add_handler(CallbackQueryHandler(edit_field,             pattern=r"^editfield:"))
    application.add_handler(CallbackQueryHandler(edit_category_selected, pattern=r"^editcat:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_text))

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()