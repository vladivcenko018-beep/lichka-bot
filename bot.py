import asyncio
import sqlite3
from datetime import datetime, timedelta
from typing import List, Tuple
import pytz

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage

import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GROUP_ID = int(os.environ.get("GROUP_ID", 0))
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x]

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set")
if GROUP_ID == 0:
    raise ValueError("GROUP_ID not set")
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS not set")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Часовой пояс Киева (UTC+3)
KIEV_TZ = pytz.timezone('Europe/Kiev')

def now_kiev() -> datetime:
    """Возвращает текущее киевское время без часового пояса (naive)"""
    return datetime.now(KIEV_TZ).replace(tzinfo=None)

# ---------- БД ----------
def init_db():
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        today_minutes INTEGER DEFAULT 0,
        last_break_date TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS active_breaks (
        user_id INTEGER PRIMARY KEY,
        start_time TEXT,
        username TEXT,
        full_name TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('max_before_12', '3')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('max_after_12', '2')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('forbidden_windows', '09:00-10:00,10:45-12:00,17:00-18:00,20:45-22:00')")
    conn.commit()
    conn.close()

init_db()

# ---------- Настройки ----------
def get_setting(key: str) -> str:
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else ""

def set_setting(key: str, value: str):
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    c.execute("REPLACE INTO settings VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_forbidden_windows() -> List[Tuple[str, str]]:
    raw = get_setting("forbidden_windows")
    windows = []
    for w in raw.split(","):
        if "-" in w:
            start, end = w.strip().split("-")
            windows.append((start, end))
    return windows

def is_forbidden_now() -> bool:
    now = now_kiev().strftime("%H:%M")
    for start, end in get_forbidden_windows():
        if start <= now <= end:
            return True
    return False

def get_max_concurrent() -> int:
    now = now_kiev()
    if now.hour < 12:
        return int(get_setting("max_before_12"))
    else:
        return int(get_setting("max_after_12"))

# ---------- Пользователи ----------
def reset_daily_minutes():
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    today_str = now_kiev().date().isoformat()
    c.execute("UPDATE users SET today_minutes = 0, last_break_date = ?", (today_str,))
    conn.commit()
    conn.close()

def get_user_today_minutes(user_id: int) -> int:
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    today_str = now_kiev().date().isoformat()
    c.execute("SELECT today_minutes, last_break_date FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return 0
    if row[1] != today_str:
        c.execute("UPDATE users SET today_minutes = 0, last_break_date = ? WHERE user_id = ?", (today_str, user_id))
        conn.commit()
        conn.close()
        return 0
    conn.close()
    return row[0] or 0

def add_user_minutes(user_id: int, minutes: int):
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    today_str = now_kiev().date().isoformat()
    c.execute("INSERT OR IGNORE INTO users (user_id, today_minutes, last_break_date) VALUES (?, 0, ?)", (user_id, today_str))
    c.execute("UPDATE users SET today_minutes = today_minutes + ? WHERE user_id = ?", (minutes, user_id))
    conn.commit()
    conn.close()

def update_user_info(user_id: int, username: str, full_name: str):
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    c.execute("UPDATE users SET username = ?, full_name = ? WHERE user_id = ?", (username, full_name, user_id))
    conn.commit()
    conn.close()

# ---------- Активные перерывы ----------
def get_active_breaks() -> List[dict]:
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    c.execute("SELECT user_id, start_time, username, full_name FROM active_breaks")
    rows = c.fetchall()
    conn.close()
    result = []
    for r in rows:
        # start_time сохранён как naive, просто преобразуем
        start = datetime.fromisoformat(r[1])
        result.append({
            "user_id": r[0],
            "start": start,
            "username": r[2],
            "full_name": r[3]
        })
    return result

def start_break(user_id: int, username: str, full_name: str):
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)", (user_id, username, full_name))
    c.execute("INSERT INTO active_breaks VALUES (?, ?, ?, ?)", (user_id, now_kiev().isoformat(), username, full_name))
    conn.commit()
    conn.close()

def end_break(user_id: int) -> int:
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    c.execute("SELECT start_time FROM active_breaks WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return 0
    start = datetime.fromisoformat(row[0])
    duration = int((now_kiev() - start).total_seconds() / 60)
    duration = min(duration, 15)
    c.execute("DELETE FROM active_breaks WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    add_user_minutes(user_id, duration)
    return duration

def get_user_display_name(user_id: int, username: str, full_name: str) -> str:
    if username:
        return f"@{username}"
    elif full_name:
        return full_name
    else:
        return str(user_id)

# ---------- Текст статуса и клавиатура ----------
def get_status_text() -> str:
    active = get_active_breaks()
    max_concurrent = get_max_concurrent()
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    c.execute("SELECT SUM(today_minutes) FROM users WHERE last_break_date = ?", (now_kiev().date().isoformat(),))
    total = c.fetchone()[0] or 0
    conn.close()
    
    forbidden_now = is_forbidden_now()
    now = now_kiev()
    
    active_list = []
    for a in active:
        display = get_user_display_name(a['user_id'], a['username'], a['full_name'])
        elapsed = int((now - a['start']).total_seconds() / 60)
        active_list.append(f"• {display} — {elapsed} мин")
    
    text = f"""
🐯 *Контроль личного перерыва*  
👥 Команда онлайн-продаж БАД

📅 *Правила:*
• 60 минут в день на человека
• 15 минут за раз
• Одновременно: до 12:00 — {get_setting('max_before_12')}, после 12:00 — {get_setting('max_after_12')}

🚫 *Личка закрыта:* 09:00-10:00, 10:45-12:00, 17:00-18:00, 20:45-22:00

⏰ Сейчас на личке: {len(active)}/{max_concurrent}
🎟 Свободных мест: {max_concurrent - len(active)}
📊 Команда использовала сегодня: {total} мин

🆔 Активные:
{chr(10).join(active_list) if active_list else "никого"}

{'🔴 СЕЙЧАС ЛИЧКА ЗАКРЫТА' if forbidden_now else '🟢 Личка открыта'}
    """
    return text.strip()

def get_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚶 Уйти на личку", callback_data="start_break")],
        [InlineKeyboardButton(text="✅ Вернулся", callback_data="end_break")]
    ])

async def safe_edit_message(message, text, reply_markup, parse_mode="Markdown"):
    if message.text != text:
        try:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            if "message is not modified" not in str(e):
                raise e

# ---------- Обработчики ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🐯 *Бот контроля личного перерыва*\n\n"
        "Используй кнопки, чтобы уйти на личку или вернуться.\n\n"
        f"{get_status_text()}",
        reply_markup=get_keyboard(),
        parse_mode="Markdown"
    )

@dp.callback_query(lambda c: c.data == "start_break")
async def start_break_callback(callback: types.CallbackQuery):
    user = callback.from_user
    update_user_info(user.id, user.username or "", user.full_name or user.first_name)
    
    active = get_active_breaks()
    if any(b["user_id"] == user.id for b in active):
        await callback.answer("❌ Ты уже на личке", show_alert=True)
        return
    
    max_concurrent = get_max_concurrent()
    if len(active) >= max_concurrent:
        await callback.answer(f"❌ Нет свободных мест (макс {max_concurrent})", show_alert=True)
        return
    
    used = get_user_today_minutes(user.id)
    if used >= 60:
        await callback.answer(f"❌ Твой лимит 60 минут на сегодня, использовано {used}", show_alert=True)
        return
    
    if is_forbidden_now():
        await callback.answer("❌ Сейчас личка закрыта (запрещённое время)", show_alert=True)
        return
    
    start_break(user.id, user.username or "", user.full_name or user.first_name)
    await callback.answer("✅ Ты ушёл на личку! Не забудь вернуться через 15 мин", show_alert=True)
    await safe_edit_message(callback.message, get_status_text(), get_keyboard(), "Markdown")
    
    async def auto_return():
        await asyncio.sleep(15 * 60)
        active_after = get_active_breaks()
        if any(b["user_id"] == user.id for b in active_after):
            end_break(user.id)
            display_name = get_user_display_name(user.id, user.username or "", user.full_name or user.first_name)
            await bot.send_message(
                GROUP_ID,
                f"⏰ {display_name} пробыл на личке 15 минут. Проверить, возможно стоит поставить штраф."
            )
            try:
                await safe_edit_message(callback.message, get_status_text(), get_keyboard(), "Markdown")
            except:
                pass
    
    asyncio.create_task(auto_return())

@dp.callback_query(lambda c: c.data == "end_break")
async def end_break_callback(callback: types.CallbackQuery):
    user = callback.from_user
    active = get_active_breaks()
    if not any(b["user_id"] == user.id for b in active):
        await callback.answer("❌ Ты не на личке", show_alert=True)
    else:
        duration = end_break(user.id)
        await callback.answer(f"✅ Ты вернулся с лички (был {duration} мин)", show_alert=True)
    await safe_edit_message(callback.message, get_status_text(), get_keyboard(), "Markdown")

# ---------- Админ-команды ----------
@dp.message(Command("set_max_before_12"))
async def set_max_before_12(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        val = int(message.text.split()[1])
        set_setting("max_before_12", str(val))
        await message.answer(f"✅ До 12:00 максимум {val} человек")
    except:
        await message.answer("❌ Используй: /set_max_before_12 3")

@dp.message(Command("set_max_after_12"))
async def set_max_after_12(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        val = int(message.text.split()[1])
        set_setting("max_after_12", str(val))
        await message.answer(f"✅ После 12:00 максимум {val} человек")
    except:
        await message.answer("❌ Используй: /set_max_after_12 2")

@dp.message(Command("add_forbidden"))
async def add_forbidden(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        window = message.text.split()[1]
        current = get_setting("forbidden_windows")
        new_windows = current + f",{window}"
        set_setting("forbidden_windows", new_windows)
        await message.answer(f"✅ Добавлено закрытое окно: {window}")
    except:
        await message.answer("❌ Используй: /add_forbidden 13:00-14:00")

@dp.message(Command("remove_forbidden"))
async def remove_forbidden(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        window = message.text.split()[1]
        current = get_setting("forbidden_windows")
        windows = current.split(",")
        windows = [w.strip() for w in windows if w.strip() != window]
        set_setting("forbidden_windows", ",".join(windows))
        await message.answer(f"✅ Удалено закрытое окно: {window}")
    except:
        await message.answer("❌ Используй: /remove_forbidden 13:00-14:00")

@dp.message(Command("reset_user"))
async def reset_user(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        username = message.text.split()[1].replace("@", "")
        conn = sqlite3.connect("breaks.db")
        c = conn.cursor()
        c.execute("UPDATE users SET today_minutes = 0 WHERE username = ?", (username,))
        conn.commit()
        conn.close()
        await message.answer(f"✅ Сброшены минуты для @{username}")
    except:
        await message.answer("❌ Используй: /reset_user @username")

@dp.message(Command("stats"))
async def stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    conn = sqlite3.connect("breaks.db")
    c = conn.cursor()
    today = now_kiev().date().isoformat()
    c.execute("SELECT username, full_name, today_minutes FROM users WHERE last_break_date = ? ORDER BY today_minutes DESC", (today,))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("📊 Сегодня никто не уходил на личку")
        return
    
    text = "📊 *Статистика за сегодня:*\n"
    for username, full_name, minutes in rows:
        display = username if username else (full_name if full_name else "Без имени")
        text += f"• {display} — {minutes}/60 мин\n"
    await message.answer(text, parse_mode="Markdown")
