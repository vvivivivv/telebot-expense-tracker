"""
Google Sheets integration via gspread.

Setup:
1. Go to https://console.cloud.google.com
2. Create a project → Enable "Google Sheets API" + "Google Drive API"
3. Create a Service Account → download credentials JSON → save as credentials.json
4. Share your Google Sheet with the service account email (Editor access)
5. Set SPREADSHEET_ID in .env
"""

import logging
from datetime import datetime
import os

logger = logging.getLogger(__name__)

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS", "credentials.json")
SHEET_NAME = "Expenses"

class SheetsClient:
    def __init__(self):
        self._client = None
        self._sheet = None
        self._try_connect()

    def _try_connect(self):
        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
            self._client = gspread.authorize(creds)
            spreadsheet = self._client.open_by_key(SPREADSHEET_ID)

            # Get or create the Expenses sheet
            try:
                self._sheet = spreadsheet.worksheet(SHEET_NAME)
            except gspread.WorksheetNotFound:
                self._sheet = spreadsheet.add_worksheet(SHEET_NAME, rows=1000, cols=6)
                self._setup_header()

            logger.info("✅ Google Sheets connected.")
        except FileNotFoundError:
            logger.warning("⚠️  credentials.json not found — Sheets sync disabled.")
        except Exception as e:
            logger.warning(f"⚠️  Sheets connection failed: {e} — Sheets sync disabled.")

    def _setup_header(self):
        if self._sheet:
            self._sheet.update("A1:F1", [["ID", "Date", "Category", "Amount", "Note", "Month"]])
            self._sheet.format("A1:F1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.2},
            })

    def append_expense(self, expense_id: int, category: str, amount: float, note: str = ""):
        if not self._sheet:
            return  # Silently skip if sheets not configured

        try:
            now = datetime.now()
            row = [
                expense_id,
                now.strftime("%Y-%m-%d %H:%M"),
                category,
                round(amount, 2),
                note,
                now.strftime("%B %Y"),
            ]
            self._sheet.append_row(row, value_input_option="USER_ENTERED")
            logger.info(f"Synced expense #{expense_id} to Sheets.")
        except Exception as e:
            logger.error(f"Sheets append failed: {e}")

    def update_expense_field(
        self,
        expense_id: int,
        category:   str   = None,
        amount:     float = None,
        note:       str   = None,
        created_at: str   = None,
    ):
    
        if not self._sheet:
            return
        try:
            import gspread
            cell = self._sheet.find(str(expense_id), in_column=1)
            if not cell:
                logger.warning(f"Expense #{expense_id} not found in Sheets.")
                return
            row = cell.row

            if created_at is not None:
                new_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                self._sheet.update_cell(row, 2, new_dt.strftime("%Y-%m-%d %H:%M"))
                self._sheet.update_cell(row, 6, new_dt.strftime("%B %Y"))
            if category is not None:
                self._sheet.update_cell(row, 3, category)
            if amount is not None:
                self._sheet.update_cell(row, 4, round(amount, 2))
            if note is not None:
                self._sheet.update_cell(row, 5, note)

            logger.info(f"Updated expense #{expense_id} in Sheets.")
        except Exception as e:
            logger.error(f"Sheets update failed: {e}")

    def delete_expense_row(self, expense_id: int):
        if not self._sheet:
            return
        try:
            cell = self._sheet.find(str(expense_id), in_column=1)
            if not cell:
                logger.warning(f"Expense #{expense_id} not found in Sheets for deletion.")
                return
            self._sheet.delete_rows(cell.row)
            logger.info(f"Deleted expense #{expense_id} from Sheets.")
        except Exception as e:
            logger.error(f"Sheets delete failed: {e}")

    @property
    def connected(self) -> bool:
        return self._sheet is not None