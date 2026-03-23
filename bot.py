import asyncio
import re
import os
from io import BytesIO
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, Message
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

DRAFT_CHANNEL = os.getenv('DRAFT_CHANNEL', '')
PUBLIC_CHANNEL = os.getenv('PUBLIC_CHANNEL', '')
SOURCE_CHANNELS = os.getenv('SOURCE_CHANNELS', '').split(',')

# Проверка
if not all([API_ID, API_HASH, PHONE_NUMBER, BOT_TOKEN, ADMIN_ID, DRAFT_CHANNEL, PUBLIC_CHANNEL, SOURCE_CHANNELS]):
    logging.error("Ошибка: не все переменные окружения заданы!")
    exit(1)

def parse_channel(channel: str):
    channel = channel.strip()
    if channel.startswith('-100') or (channel.lstrip('-').isdigit()):
        return int(channel)
    return channel

DRAFT_CHANNEL_ID = parse_channel(DRAFT_CHANNEL)
PUBLIC_CHANNEL_ID = parse_channel(PUBLIC_CHANNEL)
SOURCE_CHANNELS = [parse_channel(ch) for ch in SOURCE_CHANNELS if ch.strip()]

# Хранилище для данных медиа
draft_posts = {}  # {message_id: {'media': [...], 'text': '...', 'source': '...'}}

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
            draft_message_id = int(query.data.split("_")[1])
            post_data = draft_posts.get(draft_message_id)
            
            if not post_data:
                await query.answer("Пост не найден!")
                return
            
            # Берем сохраненный текст (уже обновленный через обработчик редактирования)
            current_text = post_data.get("text", "")
            
            print(f"📝 Публикуем текст: {current_text[:100]}...")
            
            # Если есть медиа, публикуем
            if post_data["media"]:
                media_group = []
                
                for i, media in enumerate(post_data["media"]):
                    caption = current_text if i == 0 else ""
                    
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
                            chat_id=PUBLIC_CHANNEL_ID,
                            media=media_group
                        )
                    else:
                        if media_group[0]["type"] == "photo":
                            await context.bot.send_photo(
                                chat_id=PUBLIC_CHANNEL_ID,
                                photo=BytesIO(post_data["media"][0]["data"]),
                                caption=current_text
                            )
                        else:
                            await context.bot.send_video(
                                chat_id=PUBLIC_CHANNEL_ID,
                                video=BytesIO(post_data["media"][0]["data"]),
                                caption=current_text
                            )
                    print(f"✅ Опубликовано в канал")
                    
                except Exception as e:
                    print(f"Ошибка публикации: {e}")
                    await query.answer(f"Ошибка: {e}")
                    return
            
            else:
                # Только текст
                try:
                    await context.bot.send_message(
                        chat_id=PUBLIC_CHANNEL_ID,
                        text=current_text
                    )
                    print(f"✅ Опубликовано в канал")
                except Exception as e:
                    print(f"Ошибка публикации: {e}")
                    await query.answer(f"Ошибка: {e}")
                    return
            
            # Меняем кнопку
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
    
    # Получаем каналы для мониторинга
    channels = []
    for ch in SOURCE_CHANNELS:
        try:
            entity = await client.get_entity(ch)
            channels.append(entity)
            print(f"📢 Мониторинг: {entity.title}")
        except Exception as e:
            print(f"❌ Ошибка {ch}: {e}")
    
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
    
    # Проверяем публичный канал
    try:
        public_entity = await app.bot.get_chat(PUBLIC_CHANNEL_ID)
        print(f"📢 Публикация: {public_entity.title}")
    except Exception as e:
        print(f"❌ Ошибка доступа к публичному каналу: {e}")
        return
    
    # Обработчик новых сообщений из исходных каналов
    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        msg = event.message
        
        # Игнорируем альбомы
        if msg.grouped_id:
            print(f"⏭️ Пропущен альбом из {msg.chat.title}")
            return
        
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
        
        if not original_text and not media_data:
            return
        
        await send_to_draft(app, original_text, media_data, media_type, msg.chat.title)
    
    # Обработчик редактирования сообщений в черновике
    @client.on(events.MessageEdited(chats=[DRAFT_CHANNEL_ID]))
    async def edit_handler(event):
        msg = event.message
        
        # Проверяем, есть ли этот пост в нашем хранилище
        if msg.id in draft_posts:
            # Обновляем текст
            new_text = msg.text or msg.caption or ""
            draft_posts[msg.id]["text"] = clean_text(new_text)
            print(f"✏️ Обновлен текст поста {msg.id}: {new_text[:50]}...")
    
    async def send_to_draft(app, text, media_data, media_type, chat_title):
        cleaned_text = clean_text(text)
        
        print(f"\n📥 {chat_title} -> черновик")
        
        post_data = {
            "text": cleaned_text,
            "media": [{"type": media_type, "data": media_data}] if media_data else [],
            "source": chat_title
        }
        
        try:
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
            print(f"📝 Текст: {cleaned_text[:100]}...")
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    print("\n🚀 Мониторинг запущен!")
    print(f"📝 Черновики: {draft_entity.title}")
    print(f"📢 Публикация: {public_entity.title}")
    print("\n💡 Как работает:")
    print("   1. Посты из исходных каналов попадают в черновик")
    print("   2. Вы редактируете текст прямо в канале-черновике")
    print("   3. Бот автоматически обновляет сохраненный текст")
    print("   4. Нажимаете 'Опубликовать' - публикуется ОТРЕДАКТИРОВАННЫЙ текст")
    print("   5. Кнопка 'Удалить' удаляет черновик\n")
    
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