from telethon import TelegramClient, events
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def test():
    client = TelegramClient('session', int(os.getenv('API_ID')), os.getenv('API_HASH'))
    await client.start(phone=os.getenv('PHONE_NUMBER'))
    
    # Получаем каналы
    channels = []
    for ch in os.getenv('SOURCE_CHANNELS').split(','):
        try:
            entity = await client.get_entity(ch.strip())
            channels.append(entity)
            print(f"✅ Слушаю: {entity.title}")
        except Exception as e:
            print(f"❌ {ch}: {e}")
    
    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        print(f"\n🔔 НОВОЕ СООБЩЕНИЕ!")
        print(f"Канал: {event.chat.title}")
        print(f"Текст: {event.message.text[:200] if event.message.text else '[Медиа]'}")
    
    print("\n✅ Ожидаю новые сообщения...")
    print("💡 Напишите что-нибудь в @test_pub_bot_pr\n")
    
    await client.run_until_disconnected()

asyncio.run(test())