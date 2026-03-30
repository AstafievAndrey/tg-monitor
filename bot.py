import asyncio
import re
import hashlib
import sys
import io
from datetime import datetime
from io import BytesIO
from typing import Dict, Any

from config_loader import config
from text_cleaner import TextCleaner
from database import db

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from telegram.error import TimedOut, NetworkError

import logging
import feedparser
from bs4 import BeautifulSoup
import httpx

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

# HTTP клиент для RSS
http_client = httpx.AsyncClient(timeout=30.0)

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
def format_final_text(content: str, hashtags: list) -> str:
    """Формирует финальный текст для публикации"""
    result = content.strip()
    
    if hashtags:
        hashtags_text = ' '.join([f"#{tag.strip()}" for tag in hashtags if tag.strip()])
        result += f"\n\n{hashtags_text}"
    
    return result

# ==================== ГЕНЕРАЦИЯ УНИКАЛЬНОГО ID ====================
def generate_post_id(source: str, identifier: str) -> str:
    """Генерирует уникальный ID для поста"""
    return hashlib.md5(f"{source}:{identifier}".encode()).hexdigest()

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
                            
                            if cleaned_text:
                                await send_to_draft(
                                    application=application,
                                    text=cleaned_text,
                                    source_title=entity.title,
                                    channel_config=channel_config,
                                    post_type="telegram"
                                )
                                
                                db.add_processed(post_id, {
                                    'source': entity.title,
                                    'message_id': msg.id,
                                    'channel': channel_config['name']
                                })
                            
                            last_message_ids[entity.id] = msg.id
                            
            except Exception as e:
                logger.error(f"Polling error: {e}")
            
            await asyncio.sleep(CHECK_INTERVAL)
    
    asyncio.create_task(check_new_messages())
    logger.info(f"Telegram monitoring started (interval: {CHECK_INTERVAL} sec)")

# ==================== МОНИТОРИНГ RSS ЛЕНТ ====================
async def monitor_rss_feeds(application):
    """Мониторинг RSS лент"""
    all_rss_feeds = config.get_all_rss_feeds()
    
    if not all_rss_feeds:
        logger.info("No RSS feeds configured")
        return
    
    logger.info(f"RSS monitoring started ({len(all_rss_feeds)} sources)")
    
    while True:
        try:
            for feed_item in all_rss_feeds:
                channel_config = feed_item['channel_config']
                feed_name = feed_item['feed_name']
                feed_url = feed_item['feed_url']
                feed_hashtags = feed_item['feed_hashtags']
                
                logger.info(f"[RSS] Checking: {feed_name} -> {channel_config['name']}")
                
                try:
                    response = await http_client.get(feed_url)
                    
                    if response.status_code != 200:
                        logger.error(f"Failed to load {feed_name}: {response.status_code}")
                        continue
                    
                    feed_data = feedparser.parse(response.text)
                    
                    for entry in feed_data.entries[:5]:
                        entry_link = entry.get('link', '')
                        entry_title = entry.get('title', '')
                        post_id = generate_post_id(feed_name, f"{entry_link}:{entry_title}")
                        
                        if db.is_processed(post_id):
                            continue
                        
                        title = entry.get('title', '')
                        link = entry.get('link', '')
                        summary = entry.get('summary', '')
                        published = entry.get('published', '')
                        
                        if summary:
                            soup = BeautifulSoup(summary, 'html.parser')
                            clean_summary = soup.get_text(separator=' ', strip=True)
                            if len(clean_summary) > 500:
                                clean_summary = clean_summary[:500] + '...'
                        else:
                            clean_summary = ''
                        
                        text = f"{title}\n\n"
                        if published:
                            text += f"Date: {published}\n\n"
                        if clean_summary:
                            text += f"{clean_summary}\n\n"
                        text += f"Link: {link}"
                        
                        cleaned_text = TextCleaner.clean(text)
                        
                        if cleaned_text:
                            await send_to_draft(
                                application=application,
                                text=cleaned_text,
                                source_title=feed_name,
                                channel_config=channel_config,
                                post_type="rss",
                                custom_hashtags=feed_hashtags
                            )
                            
                            db.add_processed(post_id, {
                                'source': feed_name,
                                'title': title,
                                'link': link
                            })
                            
                            logger.info(f"[OK] New RSS post: {title[:50]}...")
                            
                except Exception as e:
                    logger.error(f"Parse error {feed_name}: {e}")
            
            db.clean_old(days=7)
            
        except Exception as e:
            logger.error(f"RSS monitoring error: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL * 6)

# ==================== ОТПРАВКА В ЧЕРНОВИК ====================
async def send_to_draft(application, text: str, source_title: str, channel_config: dict, 
                        post_type: str = "telegram", custom_hashtags: list = None):
    """Отправляет пост в черновик с кнопками"""
    
    prefix = f"[{channel_config['name']}] {post_type.upper()}: {source_title}\n\n"
    full_text = prefix + text
    
    post_data = {
        "text": text,
        "source": source_title,
        "channel_config": channel_config,
        "post_type": post_type,
        "custom_hashtags": custom_hashtags or []
    }
    
    try:
        sent_msg = await safe_send_message(
            application.bot,
            DRAFT_CHANNEL_ID,
            full_text
        )
        
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
        logger.info(f"Post sent to draft (ID: {sent_msg.message_id})")
        
    except Exception as e:
        logger.error(f"Error sending to draft: {e}")

# ==================== ОБРАБОТЧИК КНОПОК ====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    
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
            
            content = post_data.get("text", "")
            hashtags = channel_config['hashtags']
            
            if post_data.get("custom_hashtags"):
                hashtags = hashtags + post_data["custom_hashtags"]
            
            final_text = format_final_text(content, hashtags)
            target_channel_id = channel_config.get('public_channel_id')
            
            logger.info(f"Publishing to {channel_config['name']} ({target_channel_id})")
            
            try:
                await safe_send_message(
                    context.bot,
                    target_channel_id,
                    final_text,
                    disable_web_page_preview=False
                )
                logger.info(f"Published to {channel_config['name']}")
                
                await context.bot.delete_message(
                    chat_id=DRAFT_CHANNEL_ID,
                    message_id=draft_message_id
                )
                
                if draft_message_id in draft_posts:
                    del draft_posts[draft_message_id]
                
                await query.answer("Post published and removed from draft!")
                
            except Exception as e:
                logger.error(f"Publish error: {e}")
                await query.answer(f"Error: {e}")
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
                logger.info(f"   RSS sources: {len(channel_config.get('rss_feeds', []))}")
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
    asyncio.create_task(monitor_rss_feeds(application))
    
    logger.info("\n" + "="*60)
    logger.info("MONITORING STARTED!")
    logger.info("="*60)
    logger.info(f"Draft channel: {draft_entity.title}")
    logger.info(f"Check interval: {CHECK_INTERVAL} sec")
    logger.info("")
    logger.info("HOW IT WORKS:")
    logger.info("   1. New posts from Telegram/RSS go to draft channel")
    logger.info("   2. You can edit text in draft channel")
    logger.info("   3. When publishing, hashtags from config are added")
    logger.info("   4. Source links are NOT added")
    logger.info("   5. Anyone can publish/delete posts")
    logger.info("="*60 + "\n")
    
    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("\nStopping...")
    finally:
        await application.stop()
        await http_client.aclose()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram stopped")
    except Exception as e:
        print(f"\nError: {e}")