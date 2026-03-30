import re
from typing import Tuple, List

class TextCleaner:
    """Очистка текста от рекламы и лишних элементов"""
    
    # Список слов и фраз для удаления (реклама, призывы)
    AD_KEYWORDS = [
        r'реклама',
        r'промо',
        r'партнёрка',
        r'партнерка',
        r'sponsored',
        r'реклам',
        r'💰',
        r'🔗',
        r'📢',
        r'👉',
        r'👇',
        r'Подпишись',
        r'Присоединяйся',
        r'Подписывайся',
        r'Источник',
        r'Ссылка',
        r'Переходи',
        r'Поддержать',
        r'Донат',
        r'🔥',
        r'❗️',
        r'🔔',
        r'🔊',
        r'⚡️',
        r'💥',
        r'🎯'
    ]
    
    # Шаблоны для удаления
    PATTERNS = [
        (r'@\w+', ''),  # Упоминания
        (r'https?://t\.me/\S+', ''),  # Ссылки на Telegram
        (r'https?://\S+', ''),  # Все остальные ссылки
        (r'[【\[].*?[】\]]', ''),  # Скобки с текстом
        (r'[\(（].*?[\)）]', ''),  # Круглые скобки
        (r'^[🔥📢❗️🔔🔊⚡️💥🎯💰🔗👉👇]*\s*', ''),  # Эмодзи в начале
    ]
    
    @classmethod
    def clean(cls, text: str) -> str:
        """Полная очистка текста"""
        if not text:
            return ""
        
        # Применяем все шаблоны
        for pattern, replacement in cls.PATTERNS:
            text = re.sub(pattern, replacement, text)
        
        # Удаляем строки с рекламными ключевыми словами
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Проверяем, содержит ли строка рекламные слова
            has_ad = False
            for keyword in cls.AD_KEYWORDS:
                if re.search(keyword, line, re.IGNORECASE):
                    has_ad = True
                    break
            
            if not has_ad:
                cleaned_lines.append(line)
        
        text = '\n'.join(cleaned_lines)
        
        # Удаляем пустые строки
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        return text.strip()
    
    @classmethod
    def extract_media(cls, msg) -> Tuple[bytes, str]:
        """Извлекает медиа из сообщения"""
        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
        
        media_data = None
        media_type = None
        
        if msg.media:
            if isinstance(msg.media, MessageMediaPhoto):
                media_type = "photo"
                try:
                    # В реальном коде здесь будет загрузка
                    pass
                except Exception:
                    pass
            elif isinstance(msg.media, MessageMediaDocument):
                if msg.media.document and hasattr(msg.media.document, 'mime_type'):
                    if 'video' in msg.media.document.mime_type:
                        media_type = "video"
                        try:
                            # В реальном коде здесь будет загрузка
                            pass
                        except Exception:
                            pass
        
        return media_data, media_type