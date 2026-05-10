import logging
import os
from datetime import time, datetime
import pytz
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from database import Database
from keeper_ai import KeeperAI
from handlers import handle_message, start_command, _fire_reminder
import jobs

load_dotenv()

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TZ = pytz.timezone('America/Guatemala')


def setup_jobs(job_queue, db):
    # --- Daily schedule ---
    job_queue.run_daily(jobs.wake_up_check,               time(6, 30, tzinfo=TZ),  name='wake_up')
    job_queue.run_daily(jobs.bcblurrr_reminder,           time(6, 50, tzinfo=TZ),  name='bcblurrr_reminder')
    job_queue.run_daily(jobs.bcblurrr_wrapup,             time(9,  0, tzinfo=TZ),  name='bcblurrr_wrapup')
    job_queue.run_daily(jobs.schedule_daily_reading_nudge, time(8, 55, tzinfo=TZ), name='schedule_reading_nudge')
    job_queue.run_daily(jobs.evening_recap,               time(21, 30, tzinfo=TZ), name='evening_recap')
    job_queue.run_daily(jobs.bedtime_reminder,            time(22,  0, tzinfo=TZ), name='bedtime')

    # --- Monthly/yearly (run daily, date-checked inside each job) ---
    job_queue.run_daily(jobs.invoice_bcblurrr,    time(9, 0, tzinfo=TZ),  name='invoice_bcblurrr')
    job_queue.run_daily(jobs.factura_and_taxes,   time(9, 0, tzinfo=TZ),  name='factura_taxes')
    job_queue.run_daily(jobs.credit_card_reminder, time(9, 0, tzinfo=TZ), name='credit_card')
    job_queue.run_daily(jobs.content_reminders,   time(18, 0, tzinfo=TZ), name='content_reminders')
    job_queue.run_daily(jobs.dental_reminder,     time(9, 0, tzinfo=TZ),  name='dental')

    # --- One-time reminders poller (every 5 min) ---
    job_queue.run_repeating(jobs.check_pending_reminders, interval=300, first=15, name='reminders_poll')

    # --- Re-register unsent one-time reminders from DB after restart ---
    now = datetime.now(TZ)
    for reminder_id, message, remind_at in db.get_unsent_reminders():
        try:
            dt = datetime.fromisoformat(remind_at)
            if dt.tzinfo is None:
                dt = TZ.localize(dt)
            if dt > now:
                job_queue.run_once(
                    _fire_reminder,
                    when=dt,
                    data={'id': reminder_id, 'message': message},
                    name=f'reminder_{reminder_id}'
                )
        except Exception as e:
            logger.error(f"Failed to re-register reminder {reminder_id}: {e}")


def main():
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not set. Check your .env or Railway environment variables.")

    gemini_key = os.getenv('GEMINI_API_KEY')
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    db = Database()
    db.init()

    ai = KeeperAI(db)

    app = Application.builder().token(token).build()
    app.bot_data['db'] = db
    app.bot_data['ai'] = ai

    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    setup_jobs(app.job_queue, db)

    logger.info("Keeper is online.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
