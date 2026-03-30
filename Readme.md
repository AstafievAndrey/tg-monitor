# Создайте виртуальное окружение

python3 -m venv venv

# Активируйте виртуальное окружение

source venv/bin/activate

# Обновите pip

pip install --upgrade pip

# Установите зависимости

pip install python-telegram-bot telethon python-dotenv feedparser beautifulsoup4 httpx

# Убедитесь, что виртуальное окружение активировано

source venv/bin/activate

# Запуск бота

python3 bot.py
