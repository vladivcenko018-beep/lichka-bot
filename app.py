import os
import asyncio
import threading
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!"

@app.route('/health')
def health():
    return "OK", 200

def run_bot():
    from bot import start_bot
    asyncio.run(start_bot())

if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    # Запускаем Flask для пингов Render
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
