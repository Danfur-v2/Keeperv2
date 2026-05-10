import json
import re
import os
import logging
from datetime import datetime
import pytz
import google.generativeai as genai

logger = logging.getLogger(__name__)
TZ = pytz.timezone('America/Guatemala')

SYSTEM_PROMPT = """You are Keeper, a personal productivity coach and life assistant.

PERSONALITY: Direct, warm, no fluff. You hold the user accountable without being annoying. You celebrate consistency and push gently when they slip. You don't lecture twice about the same thing. You speak like a trusted friend who takes their goals seriously. Keep responses concise — no walls of text.

USER PROFILE:
- Timezone: Guatemala (UTC-6)
- Jobs:
  * BcBlurrr — top priority, highest pay. Deep work block weekdays 7–9am. Invoice sent every 1st of month.
  * Crypto social account — content creation only, last weekend of each month.
  * Kasemal — content creation, second-to-last weekend of each month. Factura sent every 25th.
  * Casa Fantasma — design object studio side business, in early development.
- Daily goals: Wake up before 9am (weekdays), sleep 10:00–10:30pm, read every day, reduce short-form content consumption, protect 7–9am BcBlurrr block
- Monthly budget: 6,000 GTQ. Alert when close to or over limit.
- Short-form content scale: 1 = none consumed, 5 = way too much

CURRENT CONTEXT:
{context}

RESPONSE FORMAT — you must ALWAYS reply with valid JSON only, no markdown, no extra text:
{{
  "message": "your response to the user",
  "actions": []
}}

AVAILABLE ACTIONS (add to the actions array when the user's message implies logging or scheduling something):

Log an expense:
{{"type":"log_expense","amount":number,"currency":"GTQ or USD","category":"Food|Transport|Entertainment|Shopping|Health|Subscriptions|Work|Other","description":"string"}}

Log a reading session:
{{"type":"log_reading","duration_minutes":number,"notes":"string"}}

Mark current book as finished:
{{"type":"finish_book","notes":"string"}}

Start a new book:
{{"type":"start_book","title":"string","author":"string"}}

Log a habit:
{{"type":"log_habit","habit":"wake_up|bcblurrr|bedtime|short_form_content","value":"string","notes":"string"}}

Add a one-time reminder:
{{"type":"add_reminder","message":"string","remind_at":"YYYY-MM-DDTHH:MM:SS"}}

Add a new habit to track:
{{"type":"add_habit","name":"string","frequency":"daily|weekdays|weekends|weekly","check_in_time":"HH:MM"}}

Log journal / end-of-day mood (always include this when processing an evening recap message):
{{"type":"log_journal","text":"string","mood":"string","mood_score":1-5,"major_event":"string or null"}}

The actions array can be empty [] if nothing needs logging.
Always reference real numbers from the context (streaks, spending) when relevant — don't make up data."""


class KeeperAI:
    def __init__(self, db):
        self.db = db
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        self.model = genai.GenerativeModel('gemini-1.5-flash')

    def _build_context(self):
        now = datetime.now(TZ)

        logs = self.db.get_logs_last_days(7)
        logs_text = "\n".join(f"  {d} | {cat}: {val} {('— ' + notes) if notes else ''}"
                              for d, cat, val, notes in logs) or "  No recent logs"

        book = self.db.get_current_book()
        book_text = f"{book[1]} by {book[2]} (started {book[3]})" if book else "None"

        reading_streak = self.db.get_reading_streak()
        books_this_year = self.db.get_yearly_book_count()

        _, monthly_total = self.db.get_monthly_spending()
        budget_left = 6000 - monthly_total

        return (
            f"Date/time: {now.strftime('%A %B %d, %Y %H:%M')}\n\n"
            f"Habit logs last 7 days:\n{logs_text}\n\n"
            f"Current book: {book_text}\n"
            f"Reading streak: {reading_streak} days\n"
            f"Books finished this year: {books_this_year}\n\n"
            f"Monthly spending: Q{monthly_total:.0f} / Q6,000 (Q{budget_left:.0f} remaining)"
        )

    def _parse_response(self, text):
        text = text.strip()
        # Strip markdown code fences if present
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            text = match.group(1)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract a JSON object
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
        return {"message": text, "actions": []}

    def chat(self, user_message):
        context = self._build_context()
        system = SYSTEM_PROMPT.replace('{context}', context)

        history = self.db.get_recent_conversation(20)
        chat_history = []
        for role, content in history:
            gemini_role = 'model' if role == 'assistant' else 'user'
            if role == 'assistant':
                try:
                    content = json.loads(content).get('message', content)
                except Exception:
                    pass
            chat_history.append({'role': gemini_role, 'parts': [content]})

        chat = self.model.start_chat(history=chat_history)
        full_prompt = f"{system}\n\nUser: {user_message}"
        response = chat.send_message(full_prompt)
        return self._parse_response(response.text)

    def generate_scheduled_message(self, message_type):
        context = self._build_context()
        system = SYSTEM_PROMPT.replace('{context}', context)

        tasks = {
            'wake_up':           "It's 6:30am. Send a short, friendly wake-up check. Ask if they're up yet.",
            'bcblurrr_reminder': "It's 6:50am weekday. BcBlurrr deep work block starts in 10 min. Brief motivating nudge.",
            'bcblurrr_wrapup':   "It's 9:00am weekday. BcBlurrr block just ended. Ask what they got done. Keep it brief.",
            'reading_nudge':     "Send a casual, non-preachy nudge to read today. One sentence max.",
            'evening_recap':     "It's 9:30pm. Ask them to share how the day went — a few sentences is enough. Tell them you'll track mood and highlights from what they write.",
            'bedtime':           "It's 10pm. Gentle wind-down reminder. Also ask for their short-form content score (1–5 scale: 1=none, 5=way too much).",
            'invoice_bcblurrr':  "It's the 1st of the month. Remind them to send their invoice to BcBlurrr.",
            'factura_made':      "It's the 25th. Remind them to send their Factura to Made Studio.",
            'taxes':             "It's the 25th. Remind them to pay their taxes.",
            'credit_card':       "It's the 10th. Remind them to pay their credit card.",
            'crypto_content':    "The last weekend of the month is coming up. Remind them to create content for the Crypto social account.",
            'kasemal_content':   "The second-to-last weekend of the month is coming up. Remind them to create content for Kasemal.",
            'dental':            "It's February 1st. Remind them to schedule their annual dental cleaning appointment.",
        }

        task = tasks.get(message_type, "Send a helpful check-in message.")
        prompt = f"{system}\n\nTASK: {task}\n\nRespond with JSON only: {{\"message\": \"...\", \"actions\": []}}"

        try:
            response = self.model.generate_content(prompt)
            parsed = self._parse_response(response.text)
            return parsed.get('message', response.text)
        except Exception as e:
            logger.error(f"Gemini error for {message_type}: {e}")
            return self._fallback_message(message_type)

    def _fallback_message(self, message_type):
        fallbacks = {
            'wake_up':           "Good morning! Are you up yet?",
            'bcblurrr_reminder': "BcBlurrr block in 10 minutes. Get ready.",
            'bcblurrr_wrapup':   "9am — how did the BcBlurrr block go?",
            'reading_nudge':     "Have you read today?",
            'evening_recap':     "How was your day? Share a few sentences and I'll log your mood.",
            'bedtime':           "Time to wind down. Short-form content score today? (1–5)",
            'invoice_bcblurrr':  "Reminder: send your BcBlurrr invoice today.",
            'factura_made':      "Reminder: send your Factura to Made Studio + pay taxes today.",
            'taxes':             "Reminder: pay your taxes today.",
            'credit_card':       "Reminder: pay your credit card today.",
            'crypto_content':    "This weekend is Crypto content weekend.",
            'kasemal_content':   "This weekend is your Kasemal content weekend.",
            'dental':            "Reminder: schedule your dental cleaning appointment.",
        }
        return fallbacks.get(message_type, "Hey, checking in!")
