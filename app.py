import os
import asyncio
import threading
from flask import Flask
from bot import dp, bot as telegram_bot

app = Flask(name)

@app.route('/')
def home():
    return "Бот работает!"

@app.route('/health')
def health():
    return "OK", 200

def run_bot():
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)

if name == "main":
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
