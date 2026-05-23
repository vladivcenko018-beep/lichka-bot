import os
import asyncio
import threading
from flask import Flask
from bot import dp, bot

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!"

@app.route('/health')
def health():
    return "OK", 200

async def start_bot():
    """Запускает Telegram бота"""
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    loop = asyncio.new_event_loop()
    
    def run_bot():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(start_bot())
    
    threading.Thread(target=run_bot).start()
    
    # Запускаем Flask для Render
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
