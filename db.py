"""
Database layer. All storage goes to Sheets.
"""

from sheets import SheetsClient

class Database:
    def __init__(self):
        self._sheets = SheetsClient()

    def add_expense(self, category: str, amount: float, note: str = "") -> int:
        return self._sheets.add_expense(category, amount, note)

    def delete_expense(self, expense_id: int) -> bool:
        return self._sheets.delete_expense(expense_id)

    def update_expense(
        self,
        expense_id: int,
        category:   str   = None,
        amount:     float = None,
        note:       str   = None,
        created_at: str   = None,
    ) -> bool:
        return self._sheets.update_expense(
            expense_id,
            category=category,
            amount=amount,
            note=note,
            created_at=created_at,
        )

    def get_recent(self, n: int = 10):
        return self._sheets.get_recent(n)

    def monthly_summary(self, year: int, month: int):
        return self._sheets.monthly_summary(year, month)