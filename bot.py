import asyncio
import re
import os
from io import BytesIO
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO)

# ==================== КОНФИГУРАЦИЯ ====================
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')
PHONE_NUMBER = os.getenv('PHONE_NUMBER', '')

BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))

# Общий канал-черновик
DRAFT_CHANNEL = os.getenv('DRAFT_CHANNEL', '')

# Первый набор каналов (публикуется в PUBLIC_CHANNEL_1)
SOURCE_CHANNELS_1 = os.getenv('SOURCE_CHANNELS_1', '').split(',')
PUBLIC_CHANNEL_1 = os.getenv('PUBLIC_CHANNEL_1', '')
HASHTAGS_1 = os.getenv('HASHTAGS_1', '#новости').split(',')

# Второй набор каналов (публикуется в PUBLIC_CHANNEL_2)
SOURCE_CHANNELS_2 = os.getenv('SOURCE_CHANNELS_2', '').split(',')
PUBLIC_CHANNEL_2 = os.getenv('PUBLIC_CHANNEL_2', '')
HASHTAGS_2 = os.getenv('HASHTAGS_2', '#новости').split(',')

def parse_channel(channel: str):
    channel = channel.strip()
    if channel.startswith('-100') or (channel.lstrip('-').isdigit()):
        return int(channel)
    return channel

# Парсим
DRAFT_CHANNEL_ID = parse_channel(DRAFT_CHANNEL)
PUBLIC_CHANNEL_1_ID = parse_channel(PUBLIC_CHANNEL_1) if PUBLIC_CHANNEL_1 else None
PUBLIC_CHANNEL_2_ID = parse_channel(PUBLIC_CHANNEL_2) if PUBLIC_CHANNEL_2 else None

SOURCE_CHANNELS_1 = [parse_channel(ch) for ch in SOURCE_CHANNELS_1 if ch.strip()]
SOURCE_CHANNELS_2 = [parse_channel(ch) for ch in SOURCE_CHANNELS_2 if ch.strip()]

# Хранилище
draft_posts = {}  # {message_id: {"text": str, "media": list, "target_channel": int, "source": str}}
last_message_ids = {}  # {channel_id: last_message_id}

# ==================== ФОРМИРОВАНИЕ ТЕКСТА С ХЕШТЕГАМИ И ССЫЛКОЙ ====================
async def add_hashtags_and_link(text: str, target_channel_id: int, app) -> str:
    """Добавляет хештеги и ссылку на канал к тексту"""
    if not text:
        text = ""
    
    # Выбираем хештеги в зависимости от целевого канала
    if target_channel_id == PUBLIC_CHANNEL_1_ID:
        hashtags = HASHTAGS_1
        channel_link = PUBLIC_CHANNEL_1
    elif target_channel_id == PUBLIC_CHANNEL_2_ID:
        hashtags = HASHTAGS_2
        channel_link = PUBLIC_CHANNEL_2
    else:
        hashtags = []
        channel_link = None
    
    # Формируем хештеги
    hashtags_text = ' '.join([f"#{tag.strip()}" for tag in hashtags if tag.strip()])
    
    # Формируем финальный текст
    result = text.strip()
    
    if hashtags_text:
        result += f"\n\n{hashtags_text}"
    
    # Добавляем ссылку на канал, если она указана
    if channel_link:
        # Получаем username канала для ссылки
        try:
            # Если channel_link это ID или ссылка, получаем username
            if isinstance(channel_link, int) or str(channel_link).isdigit() or str(channel_link).startswith('-100'):
                chat = await app.bot.get_chat(channel_link)
                if chat.username:
                    result += f"\n\n@{chat.username}"
                else:
                    # Если нет username, используем инвайт-ссылку
                    result += f"\n\n[Канал](https://t.me/{chat.id})"
            elif channel_link.startswith('@'):
                result += f"\n\n{channel_link}"
            elif channel_link.startswith('https://t.me/'):
                result += f"\n\n{channel_link}"
            else:
                result += f"\n\n@{channel_link}"
        except:
            # Если не удалось получить информацию, просто добавляем как есть
            if channel_link.startswith('@'):
                result += f"\n\n{channel_link}"
            elif channel_link.startswith('https://'):
                result += f"\n\n{channel_link}"
            else:
                result += f"\n\n@{channel_link}"
    
    return result.strip()

# ==================== ОЧИСТКА ТЕКСТА ====================
def clean_text(text: str) -> str:
    if not text:
        return ""
    
    text = re.sub(r'@\w+', '', text)
    text = re.sub(r'https?://t\.me/\S+', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[【\[].*?[】\]]', '', text)
    text = re.sub(r'[\(（].*?[\)）]', '', text)
    text = re.sub(r'Подпишись.*?(?:\n|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Присоединяйся.*?(?:\n|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Подписывайся.*?(?:\n|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Источник[:：].*?(?:\n|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^[🔥📢❗️🔔🔊⚡️💥🎯]*\s*', '', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    return text.strip()

# ==================== ОБРАБОТЧИК КНОПОК ====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    try:
        if query.data.startswith("publish_"):
            parts = query.data.split("_")
            draft_message_id = int(parts[1])
            post_data = draft_posts.get(draft_message_id)
            
            if not post_data:
                await query.answer("Пост не найден!")
                return
            
            # Берем целевой канал из данных поста
            target_channel = post_data.get("target_channel")
            if not target_channel:
                await query.answer("Не указан канал для публикации!")
                return
            
            # Получаем текст с хештегами и ссылкой
            current_text = post_data.get("text", "")
            final_text = await add_hashtags_and_link(current_text, target_channel, context.bot)
            
            print(f"📝 Публикуем в канал {target_channel}")
            print(f"Текст: {final_text[:100]}...")
            
            if post_data["media"]:
                media_group = []
                
                for i, media in enumerate(post_data["media"]):
                    caption = final_text if i == 0 else ""
                    
                    if media["type"] == "photo":
                        media_group.append(InputMediaPhoto(
                            media=BytesIO(media["data"]),
                            caption=caption
                        ))
                    elif media["type"] == "video":
                        media_group.append(InputMediaVideo(
                            media=BytesIO(media["data"]),
                            caption=caption
                        ))
                
                try:
                    if len(media_group) > 1:
                        await context.bot.send_media_group(
                            chat_id=target_channel,
                            media=media_group
                        )
                    else:
                        if media_group[0]["type"] == "photo":
                            await context.bot.send_photo(
                                chat_id=target_channel,
                                photo=BytesIO(post_data["media"][0]["data"]),
                                caption=final_text
                            )
                        else:
                            await context.bot.send_video(
                                chat_id=target_channel,
                                video=BytesIO(post_data["media"][0]["data"]),
                                caption=final_text
                            )
                    print(f"✅ Опубликовано в канал {target_channel}")
                    
                except Exception as e:
                    print(f"Ошибка публикации: {e}")
                    await query.answer(f"Ошибка: {e}")
                    return
            
            else:
                try:
                    await context.bot.send_message(
                        chat_id=target_channel,
                        text=final_text
                    )
                    print(f"✅ Опубликовано в канал {target_channel}")
                except Exception as e:
                    print(f"Ошибка публикации: {e}")
                    await query.answer(f"Ошибка: {e}")
                    return
            
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Опубликовано", callback_data="done")
                ]])
            )
            await query.answer("Пост опубликован!")
                
        elif query.data.startswith("delete_"):
            draft_message_id = int(query.data.split("_")[1])
            
            try:
                await context.bot.delete_message(
                    chat_id=DRAFT_CHANNEL_ID,
                    message_id=draft_message_id
                )
                if draft_message_id in draft_posts:
                    del draft_posts[draft_message_id]
                await query.answer("Черновик удален")
            except Exception as e:
                await query.answer(f"Ошибка: {e}")
                
    except Exception as e:
        print(f"Ошибка: {e}")
        await query.answer("Произошла ошибка")

# ==================== ЗАПУСК ====================
async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(button_handler))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("🤖 Бот запущен")
    
    client = TelegramClient('session', API_ID, API_HASH)
    await client.start(phone=PHONE_NUMBER)
    print("✅ Аккаунт подключён")
    
    # Собираем все исходные каналы с их целевыми каналами
    source_configs = []
    
    # Добавляем первый набор
    for ch in SOURCE_CHANNELS_1:
        if ch:
            source_configs.append({
                "channel": ch,
                "target": PUBLIC_CHANNEL_1_ID,
                "group": 1
            })
    
    # Добавляем второй набор
    for ch in SOURCE_CHANNELS_2:
        if ch:
            source_configs.append({
                "channel": ch,
                "target": PUBLIC_CHANNEL_2_ID,
                "group": 2
            })
    
    if not source_configs:
        print("❌ Нет настроенных исходных каналов!")
        return
    
    # Получаем сущности каналов
    channels = []
    for config in source_configs:
        try:
            entity = await client.get_entity(config["channel"])
            channels.append({
                "entity": entity,
                "target": config["target"],
                "group": config["group"]
            })
            print(f"📢 Мониторинг: {entity.title} -> Канал {config['group']}")
            
            # Запоминаем последнее сообщение
            last_msg = await client.get_messages(entity, limit=1)
            if last_msg:
                last_message_ids[entity.id] = last_msg[0].id
                print(f"   Последний ID: {last_msg[0].id}")
                
        except Exception as e:
            print(f"❌ Ошибка {config['channel']}: {e}")
    
    if not channels:
        print("Нет доступных каналов")
        return
    
    # Проверяем черновик
    try:
        draft_entity = await app.bot.get_chat(DRAFT_CHANNEL_ID)
        print(f"📝 Черновик: {draft_entity.title}")
    except Exception as e:
        print(f"\n❌ Ошибка доступа к черновику: {e}")
        return
    
    # Проверяем публичные каналы
    try:
        if PUBLIC_CHANNEL_1_ID:
            public_1 = await app.bot.get_chat(PUBLIC_CHANNEL_1_ID)
            print(f"📢 Публикация канал 1: {public_1.title}")
            print(f"   Хештеги: {' '.join(HASHTAGS_1)}")
        if PUBLIC_CHANNEL_2_ID:
            public_2 = await app.bot.get_chat(PUBLIC_CHANNEL_2_ID)
            print(f"📢 Публикация канал 2: {public_2.title}")
            print(f"   Хештеги: {' '.join(HASHTAGS_2)}")
    except Exception as e:
        print(f"❌ Ошибка доступа к публичному каналу: {e}")
        return
    
    # Функция для проверки новых сообщений
    async def check_new_messages():
        print("\n🔄 Запущен polling для проверки новых сообщений...")
        while True:
            try:
                for channel_info in channels:
                    entity = channel_info["entity"]
                    target_channel = channel_info["target"]
                    
                    # Получаем последние 5 сообщений
                    messages = await client.get_messages(entity, limit=5)
                    
                    for msg in messages:
                        # Если сообщение новее сохраненного ID
                        if msg.id > last_message_ids.get(entity.id, 0):
                            print(f"\n📥 НОВОЕ СООБЩЕНИЕ из {entity.title} -> в канал {channel_info['group']}")
                            
                            # Обрабатываем сообщение
                            original_text = msg.text or ""
                            
                            media_data = None
                            media_type = None
                            
                            if msg.media:
                                if isinstance(msg.media, MessageMediaPhoto):
                                    media_type = "photo"
                                    try:
                                        media_data = await msg.download_media(bytes)
                                    except Exception as e:
                                        print(f"Ошибка фото: {e}")
                                elif isinstance(msg.media, MessageMediaDocument):
                                    if msg.media.document and hasattr(msg.media.document, 'mime_type'):
                                        if 'video' in msg.media.document.mime_type:
                                            media_type = "video"
                                            try:
                                                media_data = await msg.download_media(bytes)
                                            except Exception as e:
                                                print(f"Ошибка видео: {e}")
                            
                            # Пропускаем альбомы
                            if msg.grouped_id:
                                print(f"⏭️ Пропущен альбом из {entity.title}")
                                continue
                            
                            if original_text or media_data:
                                await send_to_draft(app, original_text, media_data, media_type, entity.title, target_channel)
                            
                            # Обновляем последний ID
                            last_message_ids[entity.id] = msg.id
                            
            except Exception as e:
                print(f"Ошибка при опросе: {e}")
            
            await asyncio.sleep(3)  # Проверяем каждые 3 секунды
    
    # Обработчик редактирования сообщений в черновике
    @client.on(events.MessageEdited(chats=[DRAFT_CHANNEL_ID]))
    async def edit_handler(event):
        msg = event.message
        if msg.id in draft_posts:
            new_text = msg.text or msg.caption or ""
            draft_posts[msg.id]["text"] = clean_text(new_text)
            print(f"✏️ Обновлен текст поста {msg.id}")
    
    async def send_to_draft(app, text, media_data, media_type, chat_title, target_channel):
        cleaned_text = clean_text(text)
        
        print(f"\n📥 {chat_title} -> черновик (будет опубликовано в канал {target_channel})")
        
        post_data = {
            "text": cleaned_text,
            "media": [{"type": media_type, "data": media_data}] if media_data else [],
            "source": chat_title,
            "target_channel": target_channel
        }
        
        try:
            # Отправляем только очищенный текст
            if media_data and media_type == "photo":
                sent_msg = await app.bot.send_photo(
                    chat_id=DRAFT_CHANNEL_ID,
                    photo=BytesIO(media_data),
                    caption=cleaned_text if cleaned_text else None
                )
            elif media_data and media_type == "video":
                sent_msg = await app.bot.send_video(
                    chat_id=DRAFT_CHANNEL_ID,
                    video=BytesIO(media_data),
                    caption=cleaned_text if cleaned_text else None
                )
            else:
                sent_msg = await app.bot.send_message(
                    chat_id=DRAFT_CHANNEL_ID,
                    text=cleaned_text if cleaned_text else "Новый пост"
                )
            
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📤 Опубликовать", callback_data=f"publish_{sent_msg.message_id}"),
                InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{sent_msg.message_id}")
            ]])
            
            await app.bot.edit_message_reply_markup(
                chat_id=DRAFT_CHANNEL_ID,
                message_id=sent_msg.message_id,
                reply_markup=keyboard
            )
            
            draft_posts[sent_msg.message_id] = post_data
            print(f"✅ В черновик (ID: {sent_msg.message_id})")
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    # Запускаем polling в фоне
    asyncio.create_task(check_new_messages())
    
    print("\n🚀 Мониторинг запущен!")
    print(f"📝 Черновик: {draft_entity.title}")
    print(f"\n💡 Как работает:")
    print("   1. Посты из исходных каналов попадают в черновик")
    print("   2. Вы редактируете текст прямо в канале-черновике")
    print("   3. При публикации автоматически добавляются хештеги и ссылка на канал")
    print("   4. Нажимаете 'Опубликовать' - пост уходит в нужный канал\n")
    
    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        print("\n👋 Остановка...")
    finally:
        await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Программа остановлена")