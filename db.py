import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional

DB_PATH = "expenses.db"


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._init()


    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


    def _init(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    category  TEXT    NOT NULL,
                    amount    REAL    NOT NULL,
                    note      TEXT    DEFAULT '',
                    created_at TEXT   DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.commit()


    def add_expense(self, category: str, amount: float, note: str = "") -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO expenses (category, amount, note) VALUES (?, ?, ?)",
                (category, round(amount, 2), note)
            )
            conn.commit()
            return cur.lastrowid


    def delete_expense(self, expense_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
            conn.commit()
            return cur.rowcount > 0


    def update_expense(
        self,
        expense_id: int,
        category: str = None,
        amount: float = None,
        note: str = None
    ) -> bool:
        fields, values = [], []
        if category is not None:
            fields.append("category = ?")
            values.append(category)
        if amount is not None:
            fields.append("amount = ?")
            values.append(round(amount, 2))
        if note is not None:
            fields.append("note = ?")
            values.append(note)
        if not fields:
            return False
        values.append(expense_id)
        with self._conn() as conn:
            cur = conn.execute(
                f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?",
                values
            )
            conn.commit()
            return cur.rowcount > 0


    def get_recent(self, n: int = 10) -> List[Tuple]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, category, amount, note, created_at FROM expenses ORDER BY id DESC LIMIT ?",
                (n,)
            ).fetchall()
        return [(r["id"], r["category"], r["amount"], r["note"], r["created_at"]) for r in rows]


    def monthly_summary(self, year: int, month: int) -> List[Tuple[str, float]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT category, SUM(amount) as total
                FROM expenses
                WHERE strftime('%Y', created_at) = ?
                  AND strftime('%m', created_at) = ?
                GROUP BY category
                ORDER BY total DESC
                """,
                (str(year), f"{month:02d}")
            ).fetchall()
        return [(r["category"], r["total"]) for r in rows]


    def all_expenses_this_month(self, year: int, month: int) -> List[Tuple]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, category, amount, note, created_at
                FROM expenses
                WHERE strftime('%Y', created_at) = ?
                  AND strftime('%m', created_at) = ?
                ORDER BY id
                """,
                (str(year), f"{month:02d}")
            ).fetchall()
        return [(r["id"], r["category"], r["amount"], r["note"], r["created_at"]) for r in rows]