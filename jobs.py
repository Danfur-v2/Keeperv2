import random
import logging
import calendar
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
TZ = pytz.timezone('America/Guatemala')


async def _send(context, text):
    db = context.bot_data['db']
    chat_id = db.get_chat_id()
    if not chat_id:
        logger.warning("No chat_id stored yet — skipping scheduled message")
        return
    await context.bot.send_message(chat_id=chat_id, text=text)


async def _ai_message(context, message_type):
    ai = context.bot_data['ai']
    try:
        return ai.generate_scheduled_message(message_type)
    except Exception as e:
        logger.error(f"AI error for {message_type}: {e}")
        return None


# --- Daily jobs ---

async def wake_up_check(context):
    msg = await _ai_message(context, 'wake_up')
    if msg:
        await _send(context, msg)


async def bcblurrr_reminder(context):
    now = datetime.now(TZ)
    if now.weekday() >= 5:  # skip weekends
        return
    msg = await _ai_message(context, 'bcblurrr_reminder')
    if msg:
        await _send(context, msg)


async def bcblurrr_wrapup(context):
    now = datetime.now(TZ)
    if now.weekday() >= 5:
        return
    msg = await _ai_message(context, 'bcblurrr_wrapup')
    if msg:
        await _send(context, msg)


async def reading_nudge(context):
    db = context.bot_data['db']
    today_logs = db.get_today_logs()
    already_read = any(cat == 'reading' for cat, _, _ in today_logs)
    if already_read:
        return
    msg = await _ai_message(context, 'reading_nudge')
    if msg:
        await _send(context, msg)


async def schedule_daily_reading_nudge(context):
    """Schedules today's reading nudge at a random time between 9am and 9pm."""
    now = datetime.now(TZ)
    hour = random.randint(9, 20)
    minute = random.randint(0, 59)
    nudge_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nudge_time <= now:
        nudge_time += timedelta(days=1)
    context.job_queue.run_once(reading_nudge, when=nudge_time, name='reading_nudge_today')


async def evening_recap(context):
    msg = await _ai_message(context, 'evening_recap')
    if msg:
        await _send(context, msg)


async def bedtime_reminder(context):
    msg = await _ai_message(context, 'bedtime')
    if msg:
        await _send(context, msg)


# --- Monthly jobs (run daily, check date inside) ---

async def invoice_bcblurrr(context):
    if datetime.now(TZ).day != 1:
        return
    msg = await _ai_message(context, 'invoice_bcblurrr')
    if msg:
        await _send(context, msg)


async def factura_and_taxes(context):
    if datetime.now(TZ).day != 25:
        return
    ai = context.bot_data['ai']
    try:
        msg_factura = ai.generate_scheduled_message('factura_made')
        msg_taxes = ai.generate_scheduled_message('taxes')
        await _send(context, msg_factura)
        await _send(context, msg_taxes)
    except Exception as e:
        logger.error(f"Error in factura_and_taxes: {e}")


async def credit_card_reminder(context):
    if datetime.now(TZ).day != 10:
        return
    msg = await _ai_message(context, 'credit_card')
    if msg:
        await _send(context, msg)


async def content_reminders(context):
    """Fires on Fridays — checks whether it's the Friday before last or second-to-last weekend."""
    now = datetime.now(TZ)
    if now.weekday() != 4:  # only on Fridays
        return

    last_sat = _last_saturday_of_month(now)
    second_last_sat = last_sat - timedelta(days=7)

    friday_before_last = last_sat - timedelta(days=1)
    friday_before_second = second_last_sat - timedelta(days=1)

    ai = context.bot_data['ai']
    if now.date() == friday_before_last.date():
        try:
            msg = ai.generate_scheduled_message('crypto_content')
            await _send(context, msg)
        except Exception as e:
            logger.error(f"crypto_content error: {e}")

    if now.date() == friday_before_second.date():
        try:
            msg = ai.generate_scheduled_message('kasemal_content')
            await _send(context, msg)
        except Exception as e:
            logger.error(f"kasemal_content error: {e}")


async def dental_reminder(context):
    now = datetime.now(TZ)
    if now.month == 2 and now.day == 1:
        msg = await _ai_message(context, 'dental')
        if msg:
            await _send(context, msg)


# --- One-time reminders poller ---

async def check_pending_reminders(context):
    db = context.bot_data['db']
    pending = db.get_pending_reminders()
    for reminder_id, message in pending:
        await _send(context, f"⏰ {message}")
        db.mark_reminder_sent(reminder_id)


# --- Helper ---

def _last_saturday_of_month(dt):
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    last_date = dt.replace(day=last_day)
    # weekday(): 5 = Saturday
    days_back = (last_date.weekday() - 5) % 7
    return last_date - timedelta(days=days_back)
