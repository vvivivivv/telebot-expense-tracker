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
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

AWAITING_AMOUNT = 0   # /categories flow
CHOOSING_ENTRY = 10  # /edit: list shown, waiting for row tap
CHOOSING_FIELD = 11  # /edit: field menu shown, waiting for field tap
AWAITING_EDIT_TEXT = 12 # /edit: waiting for new value text after field tap

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
PORT = int(os.environ.get("PORT", "10000"))

db = Database()

CATEGORIES = [
    "Food", "Transport", "Housing", "Health",
    "Entertainment", "Shopping", "Education", "Work", "Others"
]

FIELD_ALIASES = {"date": "date", "amount": "amount", "note": "note", "category": "category"}
FIELD_DISPLAY = ["Date", "Amount", "Note", "Category"]


def check_user(update: Update) -> bool:
    if ALLOWED_USER_ID and update.effective_user.id != ALLOWED_USER_ID:
        return False
    return True


def _fmt_ts(ts: str) -> str:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).strftime("%d %b %Y %H:%M")
        except ValueError:
            pass
    return ts[:16]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return
    await update.message.reply_text(
        "*Expense Tracker Bot*\n\n"
        "Commands:\n\n"
        "`/add <category> <amount> [note]` — Log an expense\n"
        "`/categories` — Pick category via buttons\n"
        "`/edit` — Edit a recent entry interactively\n"
        "`/edit <id> <field> <value>` — Edit inline\n"
        "  Fields: `Date` · `Amount` · `Note` · `Category`\n"
        "`/summary [month]` — Monthly breakdown (default: this month)\n"
        "  e.g. `/summary Mar` · `/summary 3` · `/summary 03-2026`\n"
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
            "Usage: `/add <category> <amount> [note]`\nOr use /categories to pick via buttons.",
            parse_mode="Markdown"
        )
        return
    category_input = args[0].capitalize()
    matched_category = next((c for c in CATEGORIES if category_input.lower() in c.lower()), None) or category_input
    try:
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("Amount must be a number.", parse_mode="Markdown")
        return
    note = " ".join(args[2:]) if len(args) > 2 else ""
    expense_id = db.add_expense(matched_category, amount, note)
    if expense_id == -1:
        await update.message.reply_text(
            "Failed to log expense. Google Sheets may not be connected.\n"
            "Check your credentials.json and SPREADSHEET\\_ID.",
            parse_mode="Markdown"
        )
        return

    now_str = datetime.now(SGT).strftime("%d %b %Y")
    await update.message.reply_text(
        f"*Logged!*\n\nDate: {now_str}\nCategory: {matched_category}\n"
        f"Amount: ${amount:.2f}\nNote: {note or '—'}\nID: `{expense_id}`\nSynced to Google Sheets",
        parse_mode="Markdown"
    )


async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return
    keyboard, row = [], []
    for cat in CATEGORIES:
        row.append(InlineKeyboardButton(cat, callback_data=f"cat:{cat}"))
        if len(row) == 2:
            keyboard.append(row); row = []
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
    category = context.user_data.get("pending_category", "Others")

    expense_id = db.add_expense(category, amount, note)

    if expense_id == -1:
        await update.message.reply_text(
            "Failed to log expense. Google Sheets may not be connected.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    now_str = datetime.now(SGT).strftime("%d %b %Y")
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
    args = context.args or []

    if len(args) >= 3:
        try:
            eid = int(args[0])
        except ValueError:
            await update.message.reply_text("ID must be a number.", parse_mode="Markdown")
            return
        field = FIELD_ALIASES.get(args[1].lower())
        if not field:
            valid = " · ".join(f"`{f}`" for f in FIELD_DISPLAY)
            await update.message.reply_text(
                f"Unknown field `{args[1]}`.\nValid fields: {valid}", parse_mode="Markdown"
            )
            return
        await _apply_inline_edit(update, eid, field, " ".join(args[2:]))
        return

    if len(args) > 0:
        valid = " · ".join(f"`{f}`" for f in FIELD_DISPLAY)
        await update.message.reply_text(
            f"Usage: `/edit` or `/edit <id> <field> <value>`\nFields: {valid}",
            parse_mode="Markdown"
        )
        return

    expenses = db.get_recent(5)
    if not expenses:
        await update.message.reply_text(
            "No expenses found. Google Sheets may not be connected.", parse_mode="Markdown"
        )
        return ConversationHandler.END

    keyboard = []
    for eid, cat, amount, note, ts in expenses:
        try:
            date_str = datetime.strptime(ts, "%Y-%m-%d %H:%M").strftime("%d %b")
        except Exception:
            date_str = ts[:10]
        label = f"#{eid} {cat} ${amount:.2f} {date_str}"
        if note:
            label += f" — {note[:15]}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"editpick:{eid}")])

    await update.message.reply_text(
        "*Which entry do you want to edit?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CHOOSING_ENTRY


async def _apply_inline_edit(update: Update, eid: int, field: str, value: str):
    kwargs = {}
    if field == "amount":
        try:
            kwargs["amount"] = float(value)
        except ValueError:
            await update.message.reply_text(f"`{value}` is not a valid amount.", parse_mode="Markdown")
            return
    elif field == "date":
        try:
            new_dt = datetime.strptime(value, "%d-%m-%Y")
            kwargs["created_at"] = new_dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            await update.message.reply_text(f"Use format `DD-MM-YYYY`.", parse_mode="Markdown")
            return
    elif field == "note":
        kwargs["note"] = "" if value == "-" else value
    elif field == "category":
        matched = next((c for c in CATEGORIES if value.lower() in c.lower()), None)
        kwargs["category"] = matched or value.capitalize()

    success = db.update_expense(eid, **kwargs)
    if field == "date":
        display_val = datetime.strptime(value, "%d-%m-%Y").strftime("%d %b %Y")
    elif field == "amount":
        display_val = f"${kwargs['amount']:.2f}"
    elif field == "note":
        display_val = kwargs["note"] or "—"
    else:
        display_val = kwargs.get("category", value)

    if success:
        await update.message.reply_text(
            f"*{field.capitalize()} updated!*\nEntry `#{eid}` → {display_val}\nSynced to Google Sheets",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"Could not update `#{eid}`. Use `/history` to check IDs.", parse_mode="Markdown"
        )


async def edit_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    eid = int(query.data.replace("editpick:", ""))
    expenses = db.get_recent(50)
    row = next((e for e in expenses if e[0] == eid), None)
    if not row:
        await query.edit_message_text("Entry not found.")
        return ConversationHandler.END
    _, cat, amount, note, ts = row
    context.user_data.update({
        "editing_id": eid, "editing_cat": cat,
        "editing_amount": amount, "editing_note": note, "editing_ts": ts,
    })
    keyboard = [
        [InlineKeyboardButton("Change date", callback_data="editfield:date")],
        [InlineKeyboardButton("Change amount", callback_data="editfield:amount")],
        [InlineKeyboardButton("Change note", callback_data="editfield:note")],
        [InlineKeyboardButton("Change category", callback_data="editfield:category")],
    ]
    await query.edit_message_text(
        f"*Editing entry `#{eid}`*\n\n"
        f"Date: {_fmt_ts(ts)}\nCategory: {cat}\nAmount: ${amount:.2f}\nNote: {note or '—'}\n\n"
        f"What do you want to change?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CHOOSING_FIELD


async def edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("editfield:", "")
    context.user_data["editing_field"] = field

    if field == "category":
        keyboard = []
        row = []
        for cat in CATEGORIES:
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
            f"*Current amount:* ${context.user_data['editing_amount']:.2f}\n\nSend the new amount:",
            parse_mode="Markdown")
    elif field == "note":
        await query.edit_message_text(
            f"*Current note:* {context.user_data['editing_note'] or '—'}\n\nSend the new note (or `-` to clear):",
            parse_mode="Markdown")
    elif field == "date":
        await query.edit_message_text(
            f"*Current date:* {_fmt_ts(context.user_data.get('editing_ts', ''))}\n\n"
            "Send new date as `DD-MM-YYYY`:",
            parse_mode="Markdown")
    return AWAITING_EDIT_TEXT

async def edit_category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    new_cat = query.data.replace("editcat:", "")
    eid = context.user_data.get("editing_id")

    success = db.update_expense(eid, category=new_cat)
    context.user_data.clear()
    if success:
        await query.edit_message_text(
            f"*Category updated!*\nEntry `#{eid}` → {new_cat}\nSynced to Google Sheets ✓",
            parse_mode="Markdown")
    else:
        await query.edit_message_text(f"Failed to update entry `#{eid}`.", parse_mode="Markdown")
    return ConversationHandler.END

async def handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("editing_field")
    eid   = context.user_data.get("editing_id")
    if not field or not eid:
        return ConversationHandler.END

    text = update.message.text.strip()

    if field == "amount":
        try:
            new_amount = float(text)
        except ValueError:
            await update.message.reply_text(
                "Please enter a valid number.", parse_mode="Markdown"
            )
            return AWAITING_EDIT_TEXT

        success = db.update_expense(eid, amount=new_amount)
        msg = (f"*Amount updated!*\nEntry `#{eid}` → ${new_amount:.2f}\nSynced to Google Sheets"
               if success else f"Failed to update entry `#{eid}`.")

    elif field == "note":
        new_note = "" if text == "-" else text
        success = db.update_expense(eid, note=new_note)
        msg = (f"*Note updated!*\nEntry `#{eid}` → {new_note or '—'}\nSynced to Google Sheets"
               if success else f"Failed to update entry `#{eid}`.")

    elif field == "date":
        try:
            new_dt = datetime.strptime(text, "%d-%m-%Y")
            original_ts = context.user_data.get("editing_ts", "")
            try:
                orig = datetime.strptime(original_ts, "%Y-%m-%d %H:%M")
                new_ts = new_dt.replace(hour=orig.hour, minute=orig.minute).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                new_ts = new_dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            await update.message.reply_text("Use format `DD-MM-YYYY`", parse_mode="Markdown")
            return AWAITING_EDIT_TEXT
        success = db.update_expense(eid, created_at=new_ts)
        msg = (f"*Date updated!*\nEntry `#{eid}` → {new_dt.strftime('%d %b %Y')}\nSynced to Google Sheets"
               if success else f"Failed to update entry `#{eid}`.")
    else:
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_user(update):
        return

    now  = datetime.now(SGT)
    year = now.year
    month = now.month

    if context.args:
        arg = context.args[0].strip()
        parsed = False

        if "-" in arg and len(arg) >= 6:
            try:
                parts = arg.split("-")
                month = int(parts[0])
                year  = int(parts[1])
                if not (1 <= month <= 12):
                    raise ValueError
                parsed = True
            except (ValueError, IndexError):
                pass

        if not parsed:
            try:
                month = int(arg)
                if not (1 <= month <= 12):
                    raise ValueError
                parsed = True
            except ValueError:
                pass

        if not parsed:
            month_names_full  = [m.lower() for m in ["", "January","February","March","April",
                                  "May","June","July","August","September",
                                  "October","November","December"]]
            month_names_abbr  = [m.lower() for m in ["", "Jan","Feb","Mar","Apr",
                                  "May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]]
            arg_lower = arg.lower()
            for i in range(1, 13):
                if arg_lower == month_names_full[i] or arg_lower == month_names_abbr[i]:
                    month = i
                    parsed = True
                    break

        if not parsed:
            await update.message.reply_text(
                "Could not parse month.\n\n"
                "Usage: `/summary` · `/summary Mar` · `/summary 3` · `/summary 03-2026`",
                parse_mode="Markdown"
            )
            return

    from calendar import month_abbr as _mabbr
    label = f"{_mabbr[month]} {year}"
    data  = db.monthly_summary(year, month)
    total = sum(v for _, v in data)
    if not data:
        await update.message.reply_text(
            f"⚠️ No expenses logged for *{label}*.",
            parse_mode="Markdown"
        )
        return

    lines = [f"*{label} Summary*\n"]
    for category, amount in sorted(data, key=lambda x: x[1], reverse=True):
        pct = (amount / total * 100) if total else 0
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        lines.append(f"{category}\n`{bar}` {pct:.0f}%  *${amount:.2f}*\n")
    lines.append(f"\n*Total: ${total:.2f}*")
    lines.append(f"Biggest category: {data[0][0]}")
    lines.append(f"\nSummary written to Google Sheets tab: *Summary {label}*")
    db._sheets.write_summary(year, month, data, total)
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
        await update.message.reply_text(
            "No expenses found. Google Sheets may not be connected.", parse_mode="Markdown")
        return
    lines = [f"*Last {len(expenses)} expenses:*\n"]
    for eid, cat, amount, note, ts in expenses:
        lines.append(f"`#{eid}` {cat} — *${amount:.2f}* {note or ''}\n_{_fmt_ts(ts)}_\n")
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
        await update.message.reply_text("ID must be a number.", parse_mode="Markdown")
        return
    success = db.delete_expense(eid)
    if success:
        await update.message.reply_text(f"Expense `#{eid}` deleted.\nSynced to Google Sheets ✓", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Expense `#{eid}` not found. Use `/history` to check IDs.", parse_mode="Markdown")


def main():
    application = Application.builder().token(BOT_TOKEN).build()
 
    _all_cmd_fallbacks = [
        CommandHandler("cancel", cancel),
        CommandHandler("start", start),
        CommandHandler("help", help_cmd),
        CommandHandler("add", add_expense),
        CommandHandler("categories", show_categories),
        CommandHandler("summary", summary),
        CommandHandler("history", history),
        CommandHandler("delete", delete_expense),
        CommandHandler("edit", edit),
    ]
 
    cat_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(category_selected, pattern=r"^cat:")],
        states={
            AWAITING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)],
        },
        fallbacks=_all_cmd_fallbacks,
    )
 
    # allow_reentry=True: sending /edit again while mid-flow resets the conversation instead of being silently swallowed.
    # Full command fallbacks: /add, /history etc. always escape the flow too.
    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("edit", edit)],
        states={
            CHOOSING_ENTRY: [
                CallbackQueryHandler(edit_pick, pattern=r"^editpick:"),
            ],
            CHOOSING_FIELD: [
                CallbackQueryHandler(edit_field, pattern=r"^editfield:"),
            ],
            AWAITING_EDIT_TEXT: [
                CallbackQueryHandler(edit_category_selected, pattern=r"^editcat:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_text),
            ],
        },
        fallbacks=_all_cmd_fallbacks,
        allow_reentry=True,
    )
 
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("add", add_expense))
    application.add_handler(CommandHandler("categories", show_categories))
    application.add_handler(CommandHandler("summary", summary))
    application.add_handler(CommandHandler("history", history))
    application.add_handler(CommandHandler("delete", delete_expense))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(cat_conv)
    application.add_handler(edit_conv)
 
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()