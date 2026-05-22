import os
import asyncio
from flask import Flask
from bot import dp, bot as telegram_bot

app = Flask(name)

@app.route('/')
def home():
    return "Бот работает!"

@app.route('/health')
def health():
    return "OK", 200

if name == "main":
    # Запускаем бота в том же потоке
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def start_bot():
        await dp.start_polling(telegram_bot)
    
    # Запускаем бота в фоне
    import threading
    threading.Thread(target=lambda: loop.run_until_complete(start_bot())).start()
    
    # Запускаем Flask
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
