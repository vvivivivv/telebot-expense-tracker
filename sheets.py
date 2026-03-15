"""
Google Sheets integration via gspread.

Setup:
1. Go to https://console.cloud.google.com
2. Create a project → Enable "Google Sheets API" + "Google Drive API"
3. Create a Service Account → download credentials JSON → save as credentials.json
4. Share your Google Sheet with the service account email (Editor access)
5. Set SPREADSHEET_ID in environment variables

Sheet structure:
- "Expenses Mar 2026"  — all expense rows for that month
- "Summary Mar 2026"   — category breakdown written on /summary
"""

import logging
from calendar import month_abbr
from datetime import datetime
import os
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")

logger = logging.getLogger(__name__)

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS", "credentials.json")


class SheetsClient:
    def __init__(self):
        self._client = None
        self._spreadsheet = None
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
            self._spreadsheet = self._client.open_by_key(SPREADSHEET_ID)
            logger.info("✅ Google Sheets connected.")
        except FileNotFoundError:
            logger.warning("⚠️  credentials.json not found — Sheets sync disabled.")
        except Exception as e:
            logger.warning(f"⚠️  Sheets connection failed: {e} — Sheets sync disabled.")

    def _expense_tab_name(self, year: int, month: int) -> str:
        return f"Expenses {month_abbr[month]} {year}"

    def _summary_tab_name(self, year: int, month: int) -> str:
        return f"Summary {month_abbr[month]} {year}"

    def _get_or_create_expense_tab(self, year: int, month: int):
        import gspread
        tab_name = self._expense_tab_name(year, month)
        try:
            sheet = self._spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            sheet = self._spreadsheet.add_worksheet(tab_name, rows=1000, cols=6)
            sheet.update("A1:F1", [["ID", "Date", "Category", "Amount", "Note", "Month"]])
            sheet.format("A1:F1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.2},
            })
        return sheet

    def _find_row(self, sheet, expense_id: int):
        try:
            cell = sheet.find(str(expense_id), in_column=1)
            return cell.row if cell else None
        except Exception:
            return None

    def append_expense(self, expense_id: int, category: str, amount: float, note: str = ""):
        if not self._spreadsheet:
            return
        try:
            now = datetime.now(SGT)
            sheet = self._get_or_create_expense_tab(now.year, now.month)
            row = [
                expense_id,
                now.strftime("%Y-%m-%d %H:%M"),
                category,
                round(amount, 2),
                note,
                now.strftime("%B %Y"),
            ]
            sheet.append_row(row, value_input_option="USER_ENTERED")
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
    
        if not self._spreadsheet:
            return
        try:
            sheet, row_num = self._find_expense_row_anywhere(expense_id)
            if not sheet or not row_num:
                logger.warning(f"Expense #{expense_id} not found in any Sheets tab.")
                return

            if created_at is not None:
                new_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                sheet.update_cell(row_num, 2, new_dt.strftime("%Y-%m-%d %H:%M"))
                sheet.update_cell(row_num, 6, new_dt.strftime("%B %Y"))
            if category is not None:
                sheet.update_cell(row_num, 3, category)
            if amount is not None:
                sheet.update_cell(row_num, 4, round(amount, 2))
            if note is not None:
                sheet.update_cell(row_num, 5, note)

            logger.info(f"Updated expense #{expense_id} in Sheets.")
        except Exception as e:
            logger.error(f"Sheets update failed: {e}")

    def delete_expense_row(self, expense_id: int):
        if not self._spreadsheet:
            return
        try:
            sheet, row_num = self._find_expense_row_anywhere(expense_id)
            if not sheet or not row_num:
                logger.warning(f"Expense #{expense_id} not found in Sheets for deletion.")
                return
            sheet.delete_rows(row_num)
            logger.info(f"Deleted expense #{expense_id} from Sheets.")
        except Exception as e:
            logger.error(f"Sheets delete failed: {e}")

    def write_summary(self, year: int, month: int, data: list, total: float):
        if not self._spreadsheet:
            return
        try:
            import gspread
            tab_name = self._summary_tab_name(year, month)

            try:
                summary_sheet = self._spreadsheet.worksheet(tab_name)
                summary_sheet.clear()
            except gspread.WorksheetNotFound:
                summary_sheet = self._spreadsheet.add_worksheet(tab_name, rows=50, cols=3)

            summary_sheet.update("A1:C1", [["Category", "Amount", "% of Total"]])
            summary_sheet.format("A1:C1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.2},
            })

            rows = []
            for category, amount in sorted(data, key=lambda x: x[1], reverse=True):
                pct = round((amount / total * 100), 1) if total else 0
                rows.append([category, round(amount, 2), f"{pct}%"])

            rows.append(["", "", ""])
            rows.append(["TOTAL", round(total, 2), "100%"])

            if rows:
                summary_sheet.update(f"A2:C{len(rows)+1}", rows)

            logger.info(f"Written summary tab '{tab_name}' to Sheets.")
        except Exception as e:
            logger.error(f"Sheets write_summary failed: {e}")

    def _find_expense_row_anywhere(self, expense_id: int):
        try:
            all_sheets = self._spreadsheet.worksheets()
            for sheet in all_sheets:
                if not sheet.title.startswith("Expenses "):
                    continue
                row_num = self._find_row(sheet, expense_id)
                if row_num:
                    return sheet, row_num
        except Exception as e:
            logger.error(f"Sheets search failed: {e}")
        return None, None

    @property
    def connected(self) -> bool:
        return self._spreadsheet is not None