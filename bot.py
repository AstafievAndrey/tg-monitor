import asyncio
import re
import hashlib
import sys
import io
import traceback
from io import BytesIO
from typing import Dict, Any

from config_loader import config
from text_cleaner import TextCleaner
from database import db

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

import logging

# Настройка кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================
API_ID = config.api_id
API_HASH = config.api_hash
PHONE_NUMBER = config.phone_number
BOT_TOKEN = config.bot_token
DRAFT_CHANNEL_ID = config.draft_channel_id
CHECK_INTERVAL = config.check_interval

# Хранилище для черновиков
draft_posts: Dict[int, Dict] = {}
last_message_ids: Dict[int, int] = {}

# ==================== БЕЗОПАСНАЯ ОТПРАВКА ====================
async def safe_send_message(bot, chat_id: int, text: str, **kwargs):
    """Безопасная отправка сообщения с обработкой ошибок"""
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode='Markdown',
            **kwargs
        )
    except Exception as e:
        logger.warning(f"Markdown error, sending without formatting: {e}")
        clean_text = re.sub(r'[*_`#]', '', text)
        return await bot.send_message(
            chat_id=chat_id,
            text=clean_text,
            parse_mode=None,
            **kwargs
        )

# ==================== ФОРМИРОВАНИЕ ФИНАЛЬНОГО ТЕКСТА ====================
def format_final_text(content: str, hashtags: list, channel_link: str = None) -> str:
    """Формирует финальный текст для публикации"""
    result = content.strip() if content else ""
    
    # Добавляем хештеги
    if hashtags:
        hashtags_text = ' '.join([f"#{tag.strip()}" for tag in hashtags if tag.strip()])
        if result:
            result += f"\n\n{hashtags_text}"
        else:
            result = hashtags_text
    
    # Добавляем ссылку на публичный канал в конце
    if channel_link:
        if channel_link.startswith('@'):
            channel_ref = channel_link
        elif channel_link.startswith('https://t.me/'):
            channel_ref = channel_link
        else:
            channel_ref = f"@{channel_link}"
        
        result += f"\n\n{channel_ref}"
    
    return result

# ==================== ГЕНЕРАЦИЯ УНИКАЛЬНОГО ID ====================
def generate_post_id(source: str, identifier: str) -> str:
    """Генерирует уникальный ID для поста"""
    return hashlib.md5(f"{source}:{identifier}".encode()).hexdigest()

# ==================== ИЗВЛЕЧЕНИЕ МЕДИА ====================
async def extract_media(msg) -> tuple:
    """Извлекает медиа из сообщения"""
    media_data = None
    media_type = None
    
    if not msg.media:
        return media_data, media_type
    
    try:
        if isinstance(msg.media, MessageMediaPhoto):
            media_type = "photo"
            media_data = await msg.download_media(bytes)
            if media_data and len(media_data) > 0:
                logger.info(f"Downloaded photo: {len(media_data)} bytes")
            else:
                logger.warning("Photo download returned empty data")
                media_data = None
                media_type = None
                
        elif isinstance(msg.media, MessageMediaDocument):
            if hasattr(msg.media.document, 'mime_type'):
                mime = msg.media.document.mime_type
                if 'video' in mime:
                    media_type = "video"
                    media_data = await msg.download_media(bytes)
                    if media_data and len(media_data) > 0:
                        logger.info(f"Downloaded video: {len(media_data)} bytes")
                    else:
                        logger.warning("Video download returned empty data")
                        media_data = None
                        media_type = None
                elif 'image' in mime:
                    media_type = "photo"
                    media_data = await msg.download_media(bytes)
                    if media_data and len(media_data) > 0:
                        logger.info(f"Downloaded image: {len(media_data)} bytes")
                    else:
                        logger.warning("Image download returned empty data")
                        media_data = None
                        media_type = None
    except Exception as e:
        logger.error(f"Error downloading media: {e}")
        media_data = None
        media_type = None
    
    return media_data, media_type

# ==================== МОНИТОРИНГ TELEGRAM КАНАЛОВ ====================
async def monitor_telegram_channels(client, application):
    """Мониторинг Telegram каналов"""
    channels_to_monitor = []
    
    for channel_config in config.channels_config:
        for source_channel in channel_config['source_channels']:
            if source_channel:
                channels_to_monitor.append({
                    'channel': source_channel,
                    'channel_config': channel_config
                })
    
    if not channels_to_monitor:
        logger.info("No Telegram source channels configured")
        return
    
    monitored_channels = []
    for item in channels_to_monitor:
        try:
            entity = await client.get_entity(item['channel'])
            monitored_channels.append({
                'entity': entity,
                'channel_config': item['channel_config']
            })
            logger.info(f"Monitoring: {entity.title} -> {item['channel_config']['name']}")
            
            last_msg = await client.get_messages(entity, limit=1)
            if last_msg:
                last_message_ids[entity.id] = last_msg[0].id
                
        except Exception as e:
            logger.error(f"Error with {item['channel']}: {e}")
    
    async def check_new_messages():
        while True:
            try:
                for channel_info in monitored_channels:
                    entity = channel_info['entity']
                    channel_config = channel_info['channel_config']
                    
                    messages = await client.get_messages(entity, limit=5)
                    
                    for msg in messages:
                        if msg.id > last_message_ids.get(entity.id, 0):
                            logger.info(f"New message from {entity.title} -> {channel_config['name']}")
                            
                            if msg.grouped_id:
                                logger.info("Skipping album")
                                continue
                            
                            post_id = generate_post_id(entity.title, str(msg.id))
                            
                            if db.is_processed(post_id):
                                logger.info(f"Post already processed: {post_id}")
                                continue
                            
                            original_text = msg.text or ""
                            cleaned_text = TextCleaner.clean(original_text)
                            
                            media_data, media_type = await extract_media(msg)
                            
                            if cleaned_text or media_data:
                                await send_to_draft(
                                    application=application,
                                    text=cleaned_text,
                                    media_data=media_data,
                                    media_type=media_type,
                                    source_title=entity.title,
                                    channel_config=channel_config,
                                    post_type="telegram"
                                )
                                
                                db.add_processed(post_id, {
                                    'source': entity.title,
                                    'message_id': msg.id,
                                    'channel': channel_config['name'],
                                    'has_media': media_data is not None
                                })
                            
                            last_message_ids[entity.id] = msg.id
                            
            except Exception as e:
                logger.error(f"Polling error: {e}")
            
            await asyncio.sleep(CHECK_INTERVAL)
    
    asyncio.create_task(check_new_messages())
    logger.info(f"Telegram monitoring started (interval: {CHECK_INTERVAL} sec)")

# ==================== ОТПРАВКА В ЧЕРНОВИК ====================
async def send_to_draft(application, text: str, media_data: bytes, media_type: str, 
                        source_title: str, channel_config: dict, 
                        post_type: str = "telegram", custom_hashtags: list = None):
    
    has_text = bool(text and text.strip())
    
    if has_text:
        prefix = f"[{channel_config['name']}] {post_type.upper()}: {source_title}\n\n"
        full_text = prefix + text
    else:
        full_text = f"[{channel_config['name']}] {post_type.upper()}: {source_title}"
    
    saved_media = []
    if media_data and media_type and len(media_data) > 0:
        saved_media.append({
            "type": media_type,
            "data": bytes(media_data)
        })
        logger.info(f"Saving media to draft: {media_type}, {len(media_data)} bytes")
    
    post_data = {
        "text": text if has_text else "",
        "media": saved_media,
        "source": source_title,
        "channel_config": channel_config,
        "post_type": post_type,
        "has_text": has_text,
        "custom_hashtags": custom_hashtags or []
    }
    
    try:
        sent_msg = None
        
        if saved_media:
            media = saved_media[0]
            if media["type"] == "photo":
                sent_msg = await application.bot.send_photo(
                    chat_id=DRAFT_CHANNEL_ID,
                    photo=BytesIO(media["data"]),
                    caption=full_text if full_text else None,
                    parse_mode=None
                )
            elif media["type"] == "video":
                sent_msg = await application.bot.send_video(
                    chat_id=DRAFT_CHANNEL_ID,
                    video=BytesIO(media["data"]),
                    caption=full_text if full_text else None,
                    parse_mode=None
                )
        else:
            sent_msg = await application.bot.send_message(
                chat_id=DRAFT_CHANNEL_ID,
                text=full_text if full_text else "New post",
                parse_mode=None
            )
        
        if sent_msg:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Publish", callback_data=f"publish_{sent_msg.message_id}"),
                InlineKeyboardButton("Delete", callback_data=f"delete_{sent_msg.message_id}")
            ]])
            
            await application.bot.edit_message_reply_markup(
                chat_id=DRAFT_CHANNEL_ID,
                message_id=sent_msg.message_id,
                reply_markup=keyboard
            )
            
            draft_posts[sent_msg.message_id] = post_data
            logger.info(f"Post sent to draft (ID: {sent_msg.message_id}, media: {len(saved_media)}, has_text: {has_text})")
        
    except Exception as e:
        logger.error(f"Error sending to draft: {e}")

# ==================== ОБРАБОТЧИК КНОПОК ====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    logger.info(f"Button pressed: {query.data} by user {query.from_user.id}")
    
    try:
        if query.data.startswith("publish_"):
            draft_message_id = int(query.data.split("_")[1])
            post_data = draft_posts.get(draft_message_id)
            
            if not post_data:
                await query.answer("Post not found!")
                return
            
            channel_config = post_data.get("channel_config")
            if not channel_config:
                await query.answer("Channel not specified!")
                return
            
            # Получаем данные поста
            content = post_data.get("text", "")
            has_text = post_data.get("has_text", False)
            hashtags = channel_config['hashtags']
            channel_link = channel_config.get('public_channel')
            
            # Добавляем RSS хештеги если есть
            if post_data.get("custom_hashtags"):
                hashtags = hashtags + post_data["custom_hashtags"]
            
            # Формируем финальный текст
            if has_text:
                final_text = format_final_text(content, hashtags, channel_link)
            else:
                final_text = format_final_text("", hashtags, channel_link)
            
            target_channel_id = channel_config.get('public_channel_id')
            media_list = post_data.get("media", [])
            
            logger.info(f"Publishing to {channel_config['name']} ({target_channel_id})")
            logger.info(f"Media count: {len(media_list)}, has_text: {has_text}")
            
            # Проверяем валидность медиа
            valid_media = []
            for i, media in enumerate(media_list):
                if media.get("data") and len(media["data"]) > 0:
                    valid_media.append(media)
                    logger.info(f"Media {i}: {media['type']}, {len(media['data'])} bytes")
                else:
                    logger.warning(f"Media {i} is empty or invalid")
            
            try:
                # Публикуем с медиа если есть
                if valid_media:
                    if len(valid_media) == 1:
                        media = valid_media[0]
                        logger.info(f"Sending single {media['type']}...")
                        
                        if media["type"] == "photo":
                            await context.bot.send_photo(
                                chat_id=target_channel_id,
                                photo=BytesIO(media["data"]),
                                caption=final_text if final_text else None,
                                parse_mode=None
                            )
                        elif media["type"] == "video":
                            await context.bot.send_video(
                                chat_id=target_channel_id,
                                video=BytesIO(media["data"]),
                                caption=final_text if final_text else None,
                                parse_mode=None
                            )
                    else:
                        # Группа медиа
                        logger.info(f"Sending media group with {len(valid_media)} items...")
                        media_group = []
                        for i, media in enumerate(valid_media):
                            caption = final_text if i == 0 else ""
                            if media["type"] == "photo":
                                media_group.append(InputMediaPhoto(
                                    media=BytesIO(media["data"]),
                                    caption=caption,
                                    parse_mode=None
                                ))
                            elif media["type"] == "video":
                                media_group.append(InputMediaVideo(
                                    media=BytesIO(media["data"]),
                                    caption=caption,
                                    parse_mode=None
                                ))
                        
                        if media_group:
                            await context.bot.send_media_group(
                                chat_id=target_channel_id,
                                media=media_group
                            )
                else:
                    # Только текст
                    logger.info("Sending text only...")
                    await context.bot.send_message(
                        chat_id=target_channel_id,
                        text=final_text if final_text else "New post",
                        parse_mode=None,
                        disable_web_page_preview=False
                    )
                
                logger.info(f"Successfully published to {channel_config['name']}")
                
                # Удаляем из черновика
                await context.bot.delete_message(
                    chat_id=DRAFT_CHANNEL_ID,
                    message_id=draft_message_id
                )
                
                if draft_message_id in draft_posts:
                    del draft_posts[draft_message_id]
                
                await query.answer("Post published and removed from draft!")
                
            except Exception as e:
                logger.error(f"Publish error: {e}")
                traceback.print_exc()
                await query.answer(f"Error: {str(e)[:100]}")
                return
                
        elif query.data.startswith("delete_"):
            draft_message_id = int(query.data.split("_")[1])
            
            try:
                await context.bot.delete_message(
                    chat_id=DRAFT_CHANNEL_ID,
                    message_id=draft_message_id
                )
                if draft_message_id in draft_posts:
                    del draft_posts[draft_message_id]
                await query.answer("Draft deleted")
            except Exception as e:
                logger.error(f"Delete error: {e}")
                await query.answer(f"Error: {e}")
                
    except Exception as e:
        logger.error(f"Error: {e}")
        traceback.print_exc()
        await query.answer("Error occurred")
# ==================== ЗАПУСК ====================
async def main():
    """Основная функция запуска"""
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CallbackQueryHandler(button_handler))
    
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        logger.info("Telegram bot started")
    except Exception as e:
        logger.error(f"Bot start error: {e}")
        return
    
    client = TelegramClient('session', API_ID, API_HASH)
    
    try:
        await client.start(phone=PHONE_NUMBER)
        logger.info("Telethon client connected")
    except Exception as e:
        logger.error(f"Telethon connection error: {e}")
        return
    
    try:
        draft_entity = await application.bot.get_chat(DRAFT_CHANNEL_ID)
        logger.info(f"Draft channel: {draft_entity.title}")
    except Exception as e:
        logger.error(f"Draft channel error: {e}")
        return
    
    for channel_config in config.channels_config:
        if channel_config.get('public_channel_id'):
            try:
                public_channel = await application.bot.get_chat(channel_config['public_channel_id'])
                logger.info(f"Channel '{channel_config['name']}': {public_channel.title}")
                logger.info(f"   Hashtags: {' '.join(channel_config['hashtags'])}")
                logger.info(f"   TG sources: {len(channel_config['source_channels'])}")
            except Exception as e:
                logger.error(f"Channel error {channel_config['name']}: {e}")
    
    @client.on(events.MessageEdited(chats=[DRAFT_CHANNEL_ID]))
    async def edit_handler(event):
        msg = event.message
        if msg.id in draft_posts:
            new_text = msg.text or msg.caption or ""
            lines = new_text.split('\n', 1)
            if len(lines) > 1:
                clean_content = lines[1]
            else:
                clean_content = new_text
            draft_posts[msg.id]["text"] = TextCleaner.clean(clean_content)
            logger.info(f"Updated text for post {msg.id}")
    
    await monitor_telegram_channels(client, application)
    
    logger.info("\n" + "="*60)
    logger.info("MONITORING STARTED!")
    logger.info("="*60)
    logger.info(f"Draft channel: {draft_entity.title}")
    logger.info(f"Check interval: {CHECK_INTERVAL} sec")
    logger.info("")
    logger.info("HOW IT WORKS:")
    logger.info("   1. New posts from Telegram channels go to draft channel")
    logger.info("   2. You can edit text in draft channel")
    logger.info("   3. When publishing, hashtags from config are added")
    logger.info("   4. Channel link is added at the end of each post")
    logger.info("   5. Media files are preserved and published with the post")
    logger.info("="*60 + "\n")
    
    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("\nStopping...")
    finally:
        await application.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram stopped")
    except Exception as e:
        print(f"\nError: {e}")
        traceback.print_exc()