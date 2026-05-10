import sqlite3
import os
from datetime import datetime, date, timedelta
import pytz

TZ = pytz.timezone('America/Guatemala')


class Database:
    def __init__(self):
        self.path = os.getenv('DB_PATH', 'keeper.db')

    def conn(self):
        return sqlite3.connect(self.path)

    def init(self):
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS daily_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    category TEXT NOT NULL,
                    value TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    author TEXT,
                    status TEXT DEFAULT 'reading',
                    started_date TEXT,
                    completed_date TEXT,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS reading_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER REFERENCES books(id),
                    date TEXT NOT NULL,
                    duration_minutes INTEGER,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    text TEXT,
                    mood TEXT,
                    mood_score INTEGER,
                    major_event TEXT
                );
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    amount_gtq REAL,
                    category TEXT,
                    description TEXT
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    sent INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS custom_habits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    frequency TEXT,
                    check_in_time TEXT,
                    active INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

    # --- Config ---

    def get_config(self, key, default=None):
        with self.conn() as c:
            row = c.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_config(self, key, value):
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))

    def get_chat_id(self):
        val = self.get_config('chat_id')
        return int(val) if val else None

    def set_chat_id(self, chat_id):
        self.set_config('chat_id', chat_id)

    # --- Daily logs ---

    def log_habit(self, category, value, notes=''):
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        with self.conn() as c:
            c.execute(
                "INSERT INTO daily_logs (date, category, value, notes) VALUES (?, ?, ?, ?)",
                (today, category, str(value), notes)
            )

    def get_today_logs(self):
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        with self.conn() as c:
            return c.execute(
                "SELECT category, value, notes FROM daily_logs WHERE date=?", (today,)
            ).fetchall()

    def get_logs_last_days(self, days=7):
        with self.conn() as c:
            return c.execute(
                "SELECT date, category, value, notes FROM daily_logs "
                "WHERE date >= date('now', ?) ORDER BY date DESC, id DESC",
                (f'-{days} days',)
            ).fetchall()

    def get_habit_streak(self, category):
        with self.conn() as c:
            rows = c.execute(
                "SELECT DISTINCT date FROM daily_logs "
                "WHERE category=? AND value NOT IN ('skipped','no','0') "
                "ORDER BY date DESC",
                (category,)
            ).fetchall()
        today = datetime.now(TZ).date()
        streak = 0
        for i, (d,) in enumerate(rows):
            if date.fromisoformat(d) == today - timedelta(days=i):
                streak += 1
            else:
                break
        return streak

    # --- Books ---

    def get_current_book(self):
        with self.conn() as c:
            return c.execute(
                "SELECT id, title, author, started_date FROM books "
                "WHERE status='reading' ORDER BY id DESC LIMIT 1"
            ).fetchone()

    def start_book(self, title, author=''):
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        with self.conn() as c:
            c.execute(
                "INSERT INTO books (title, author, status, started_date) VALUES (?, ?, 'reading', ?)",
                (title, author, today)
            )

    def finish_book(self, notes=''):
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        book = self.get_current_book()
        if book:
            with self.conn() as c:
                c.execute(
                    "UPDATE books SET status='completed', completed_date=?, notes=? WHERE id=?",
                    (today, notes, book[0])
                )
        return book

    def log_reading_session(self, duration_minutes, notes=''):
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        book = self.get_current_book()
        book_id = book[0] if book else None
        with self.conn() as c:
            c.execute(
                "INSERT INTO reading_sessions (book_id, date, duration_minutes, notes) VALUES (?, ?, ?, ?)",
                (book_id, today, duration_minutes, notes)
            )

    def get_reading_streak(self):
        with self.conn() as c:
            rows = c.execute(
                "SELECT DISTINCT date FROM reading_sessions ORDER BY date DESC"
            ).fetchall()
        today = datetime.now(TZ).date()
        streak = 0
        for i, (d,) in enumerate(rows):
            if date.fromisoformat(d) == today - timedelta(days=i):
                streak += 1
            else:
                break
        return streak

    def get_completed_books(self):
        with self.conn() as c:
            return c.execute(
                "SELECT title, author, started_date, completed_date FROM books "
                "WHERE status='completed' ORDER BY completed_date DESC"
            ).fetchall()

    def get_yearly_book_count(self):
        year = str(datetime.now(TZ).year)
        with self.conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM books WHERE status='completed' AND completed_date LIKE ?",
                (f'{year}%',)
            ).fetchone()
        return row[0] if row else 0

    # --- Finances ---

    def log_expense(self, amount, currency, category, description=''):
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        rate = float(self.get_config('usd_to_gtq', '7.75'))
        amount_gtq = amount if currency == 'GTQ' else round(amount * rate, 2)
        with self.conn() as c:
            c.execute(
                "INSERT INTO expenses (date, amount, currency, amount_gtq, category, description) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (today, amount, currency.upper(), amount_gtq, category, description)
            )
        return amount_gtq

    def get_monthly_spending(self, year=None, month=None):
        now = datetime.now(TZ)
        year = str(year or now.year)
        month = f'{month or now.month:02d}'
        with self.conn() as c:
            breakdown = c.execute(
                "SELECT category, SUM(amount_gtq) FROM expenses "
                "WHERE strftime('%Y',date)=? AND strftime('%m',date)=? "
                "GROUP BY category ORDER BY SUM(amount_gtq) DESC",
                (year, month)
            ).fetchall()
            total = c.execute(
                "SELECT COALESCE(SUM(amount_gtq), 0) FROM expenses "
                "WHERE strftime('%Y',date)=? AND strftime('%m',date)=?",
                (year, month)
            ).fetchone()[0]
        return breakdown, total

    # --- Journal ---

    def add_journal_entry(self, text, mood=None, mood_score=None, major_event=None):
        today = datetime.now(TZ).strftime('%Y-%m-%d')
        with self.conn() as c:
            c.execute(
                "INSERT INTO journal_entries (date, text, mood, mood_score, major_event) VALUES (?,?,?,?,?)",
                (today, text, mood, mood_score, major_event)
            )

    # --- Reminders ---

    def add_reminder(self, message, remind_at):
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO reminders (message, remind_at) VALUES (?, ?)", (message, remind_at)
            )
            return cur.lastrowid

    def get_pending_reminders(self):
        now = datetime.now(TZ).isoformat()
        with self.conn() as c:
            return c.execute(
                "SELECT id, message FROM reminders WHERE sent=0 AND remind_at <= ? ORDER BY remind_at",
                (now,)
            ).fetchall()

    def get_unsent_reminders(self):
        with self.conn() as c:
            return c.execute(
                "SELECT id, message, remind_at FROM reminders WHERE sent=0 ORDER BY remind_at"
            ).fetchall()

    def mark_reminder_sent(self, reminder_id):
        with self.conn() as c:
            c.execute("UPDATE reminders SET sent=1 WHERE id=?", (reminder_id,))

    # --- Conversation history ---

    def add_conversation(self, role, content):
        with self.conn() as c:
            c.execute(
                "INSERT INTO conversation_history (role, content) VALUES (?, ?)", (role, content)
            )

    def get_recent_conversation(self, limit=20):
        with self.conn() as c:
            rows = c.execute(
                "SELECT role, content FROM conversation_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return list(reversed(rows))
