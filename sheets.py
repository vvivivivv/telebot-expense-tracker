"""
Sheet structure per month:
- "Expenses Mar 2026"  — all expense rows for that month
- "Summary Mar 2026"   — category breakdown written on /summary

Columns: A=ID, B=Date, C=Category, D=Amount, E=Note, F=Month
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
            logger.warning("⚠️  credentials.json not found — Sheets disabled.")
        except Exception as e:
            logger.warning(f"⚠️  Sheets connection failed: {e}")

    def _expense_tab_name(self, year: int, month: int) -> str:
        return f"Expenses {month_abbr[month]} {year}"

    def _summary_tab_name(self, year: int, month: int) -> str:
        return f"Summary {month_abbr[month]} {year}"

    def _get_or_create_expense_tab(self, year: int, month: int):
        import gspread
        tab_name = self._expense_tab_name(year, month)
        try:
            return self._spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            sheet = self._spreadsheet.add_worksheet(tab_name, rows=1000, cols=6)
            sheet.update("A1:F1", [["ID", "Date", "Category", "Amount", "Note", "Month"]])
            sheet.format("A1:F1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.2},
            })
            return sheet

    def _all_expense_sheets(self):
        """Return all Expenses * worksheets."""
        try:
            return [s for s in self._spreadsheet.worksheets()
                    if s.title.startswith("Expenses ")]
        except Exception:
            return []

    def _next_id(self) -> int:
        """Return the next globally unique ID across all expense tabs."""
        max_id = 0
        for sheet in self._all_expense_sheets():
            try:
                col = sheet.col_values(1)
                for val in col[1:]:
                    try:
                        max_id = max(max_id, int(str(val).strip()))
                    except ValueError:
                        pass
            except Exception:
                pass
        return max_id + 1

    def _find_row(self, sheet, expense_id: int):
        """Return 1-indexed row number for expense_id in column A, or None."""
        try:
            for i, row in enumerate(sheet.get_all_values()):
                if row and str(row[0]).strip() == str(expense_id):
                    return i + 1
        except Exception as e:
            logger.error(f"_find_row error: {e}")
        return None

    def _find_row_anywhere(self, expense_id: int):
        """Search all Expenses tabs. Returns (sheet, row_num) or (None, None)."""
        for sheet in self._all_expense_sheets():
            row_num = self._find_row(sheet, expense_id)
            if row_num:
                return sheet, row_num
        return None, None

    def _get_full_row(self, sheet, row_num: int) -> list:
        try:
            return sheet.row_values(row_num)
        except Exception:
            return []

    def _sort_tab(self, sheet):
        """Sort data rows by date (col B), keep header pinned."""
        try:
            all_values = sheet.get_all_values()
            if len(all_values) <= 2:
                return
            data_rows = all_values[1:]
            data_rows.sort(key=lambda r: r[1] if len(r) > 1 else "")
            last_row = len(all_values)
            sheet.delete_rows(2, last_row)
            if data_rows:
                sheet.append_rows(data_rows, value_input_option="USER_ENTERED")
        except Exception as e:
            logger.error(f"Sort failed: {e}")

    def add_expense(self, category: str, amount: float, note: str = "") -> int:
        """Add a new expense. Returns the new ID."""
        if not self._spreadsheet:
            return -1
        try:
            now = datetime.now(SGT)
            expense_id = self._next_id()
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
            self._sort_tab(sheet)
            logger.info(f"Added expense #{expense_id}.")
            return expense_id
        except Exception as e:
            logger.error(f"add_expense failed: {e}")
            return -1

    def delete_expense(self, expense_id: int) -> bool:
        """Delete a row by ID. Returns True if found and deleted."""
        if not self._spreadsheet:
            return False
        try:
            sheet, row_num = self._find_row_anywhere(expense_id)
            if not sheet or not row_num:
                return False
            sheet.delete_rows(row_num)
            logger.info(f"Deleted expense #{expense_id}.")
            return True
        except Exception as e:
            logger.error(f"delete_expense failed: {e}")
            return False

    def update_expense(
        self,
        expense_id: int,
        category:   str = None,
        amount:     float = None,
        note:       str   = None,
        created_at: str   = None,
    ) -> bool:
        """Update one or more fields on an existing expense.
        If created_at changes the month, the row is moved to the correct tab.
        """
        if not self._spreadsheet:
            return False
        try:
            sheet, row_num = self._find_row_anywhere(expense_id)
            if not sheet or not row_num:
                logger.warning(f"Expense #{expense_id} not found for update.")
                return False

            logger.info(f"Updating #{expense_id} at row {row_num} in '{sheet.title}'.")

            if created_at is not None:
                try:
                    dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                    created_at = dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    pass
                new_dt  = datetime.strptime(created_at, "%Y-%m-%d %H:%M")
                new_tab = self._expense_tab_name(new_dt.year, new_dt.month)

                if new_tab != sheet.title:
                    existing = self._get_full_row(sheet, row_num)
                    sheet.delete_rows(row_num)
                    new_sheet = self._get_or_create_expense_tab(new_dt.year, new_dt.month)
                    new_row = [
                        existing[0] if existing else expense_id,
                        created_at,
                        category if category is not None else (existing[2] if len(existing) > 2 else ""),
                        round(float(amount), 2) if amount is not None else (existing[3] if len(existing) > 3 else ""),
                        note if note is not None else (existing[4] if len(existing) > 4 else ""),
                        new_dt.strftime("%B %Y"),
                    ]
                    new_sheet.append_row(new_row, value_input_option="USER_ENTERED")
                    self._sort_tab(new_sheet)
                    logger.info(f"Moved #{expense_id} to '{new_tab}'.")
                    return True
                else:
                    sheet.update_cell(row_num, 2, created_at)
                    sheet.update_cell(row_num, 6, new_dt.strftime("%B %Y"))

            if category is not None:
                sheet.update_cell(row_num, 3, category)
            if amount is not None:
                sheet.update_cell(row_num, 4, round(amount, 2))
            if note is not None:
                sheet.update_cell(row_num, 5, note)

            self._sort_tab(sheet)
            logger.info(f"Updated expense #{expense_id}.")
            return True
        except Exception as e:
            logger.error(f"update_expense failed: {e}")
            return False

    def get_recent(self, n: int = 10):
        """Return last n expenses across all tabs, sorted by date descending.
        Returns list of (id, category, amount, note, created_at).
        """
        if not self._spreadsheet:
            return []
        try:
            all_rows = []
            for sheet in self._all_expense_sheets():
                for row in sheet.get_all_values()[1:]:
                    if len(row) >= 4 and row[0].strip():
                        try:
                            all_rows.append((
                                int(row[0]),
                                row[2],
                                float(row[3]),
                                row[4] if len(row) > 4 else "",
                                row[1],
                            ))
                        except (ValueError, IndexError):
                            pass
            all_rows.sort(key=lambda r: r[4], reverse=True)
            return all_rows[:n]
        except Exception as e:
            logger.error(f"get_recent failed: {e}")
            return []

    def monthly_summary(self, year: int, month: int):
        """Return [(category, total)] for the given month, sorted by total desc."""
        if not self._spreadsheet:
            return []
        try:
            tab_name = self._expense_tab_name(year, month)
            try:
                import gspread
                sheet = self._spreadsheet.worksheet(tab_name)
            except Exception:
                return []

            totals = {}
            for row in sheet.get_all_values()[1:]:
                if len(row) >= 4 and row[0].strip():
                    try:
                        cat = row[2]
                        amount = float(row[3])
                        totals[cat] = totals.get(cat, 0) + amount
                    except (ValueError, IndexError):
                        pass

            return sorted(totals.items(), key=lambda x: x[1], reverse=True)
        except Exception as e:
            logger.error(f"monthly_summary failed: {e}")
            return []

    def write_summary(self, year: int, month: int, data: list, total: float):
        """Write monthly summary to a tab named e.g. 'Summary Mar 2026'."""
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
                summary_sheet.update(f"A2:C{len(rows) + 1}", rows)

            logger.info(f"Written summary tab '{tab_name}'.")
        except Exception as e:
            logger.error(f"write_summary failed: {e}")

    @property
    def connected(self) -> bool:
        return self._spreadsheet is not None