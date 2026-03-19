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
            all_values = sheet.get_all_values()
            for i, row in enumerate(all_values):
                if row and str(row[0]).strip() == str(expense_id):
                    return i + 1
        except Exception as e:
            logger.error(f"_find_row error: {e}")
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
            self._sort_expense_tab(sheet)
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

            logger.info(f"Found expense #{expense_id} at row {row_num} in '{sheet.title}'.")

            if created_at is not None:
                new_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                new_tab = self._expense_tab_name(new_dt.year, new_dt.month)
                current_tab = sheet.title

                if new_tab != current_tab:
                    existing = self._get_full_row(sheet, row_num)
                    sheet.delete_rows(row_num)
                    logger.info(f"Moved expense #{expense_id} from '{current_tab}' to '{new_tab}'.")

                    new_sheet = self._get_or_create_expense_tab(new_dt.year, new_dt.month)
                    updated_row = [
                        existing[0] if existing else expense_id,
                        new_dt.strftime("%Y-%m-%d %H:%M"),
                        category if category is not None else (existing[2] if len(existing) > 2 else ""),
                        round(amount, 2) if amount is not None else (existing[3] if len(existing) > 3 else ""),
                        note if note is not None else (existing[4] if len(existing) > 4 else ""),
                        new_dt.strftime("%B %Y"),
                    ]
                    
                    new_sheet.append_row(updated_row, value_input_option="USER_ENTERED")
                    self._sort_expense_tab(new_sheet)
                    logger.info(f"Re-inserted expense #{expense_id} into '{new_tab}'.")
                    return

                else:
                    sheet.update_cell(row_num, 2, new_dt.strftime("%Y-%m-%d %H:%M"))
                    sheet.update_cell(row_num, 6, new_dt.strftime("%B %Y"))

            if category is not None:
                sheet.update_cell(row_num, 3, category)
            if amount is not None:
                sheet.update_cell(row_num, 4, round(amount, 2))
            if note is not None:
                sheet.update_cell(row_num, 5, note)

            self._sort_expense_tab(sheet)
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

    def _get_full_row(self, sheet, row_num: int) -> list:
        try:
            return sheet.row_values(row_num)
        except Exception:
            return []
        
    def _sort_expense_tab(self, sheet):
        try:
            all_values = sheet.get_all_values()
            if len(all_values) <= 2:
                return
            header = all_values[0]
            data_rows = all_values[1:]
            data_rows.sort(key=lambda r: r[1] if len(r) > 1 else "")
            last_row = len(all_values)
            sheet.delete_rows(2, last_row)
            if data_rows:
                sheet.append_rows(data_rows, value_input_option="USER_ENTERED")
            logger.info(f"Sorted tab '{sheet.title}' by date.")
        except Exception as e:
            logger.error(f"Sort failed: {e}")

    @property
    def connected(self) -> bool:
        return self._spreadsheet is not None