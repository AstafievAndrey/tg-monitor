# text_cleaner.py
import re
import logging

logger = logging.getLogger(__name__)

class TextCleaner:
    
    @classmethod
    def clean(cls, text: str) -> str:
        """Очистка текста от мусора"""
        if not text:
            return ""
        
        original = text
        
        # 1. Удаляем Markdown символы
        text = re.sub(r'\*\*', '', text)
        text = re.sub(r'__', '', text)
        text = re.sub(r'\*', '', text)
        text = re.sub(r'`', '', text)
        text = re.sub(r'#+', '', text)
        
        # 2. Удаляем ссылки
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r't\.me/\S+', '', text)
        
        # 3. Удаляем упоминания (@username)
        text = re.sub(r'@\w+', '', text)
        
        # 4. Удаляем текст в скобках (любых)
        text = re.sub(r'\([^)]*\)', '', text)      # (текст)
        text = re.sub(r'\[[^\]]*\]', '', text)      # [текст]
        text = re.sub(r'\{[^}]*\}', '', text)       # {текст}
        text = re.sub(r'[【\[].*?[】\]]', '', text)  # 【текст】
        text = re.sub(r'[\(（].*?[\)）]', '', text)  # （текст）
        
        # 5. Удаляем пустые скобки, которые могли остаться
        text = re.sub(r'\(\s*\)', '', text)     # ()
        text = re.sub(r'\[\s*\]', '', text)     # []
        text = re.sub(r'\{\s*\}', '', text)     # {}
        
        # 6. Удаляем разделители везде (|, -, →, ⇒)
        text = re.sub(r'\s*[|\-→⇒]\s*', ' ', text)
        text = re.sub(r'\s+', ' ', text)  # убираем лишние пробелы после замены
        
        # 7. Удаляем кавычки и лишние знаки
        text = re.sub(r'["\'«»]', '', text)
        text = re.sub(r'\.{2,}', ' ', text)  # многоточия заменяем на пробел
        
        # 8. Удаляем эмодзи
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"  # смайлики
            u"\U0001F300-\U0001F5FF"  # символы
            u"\U0001F680-\U0001F6FF"  # транспорт
            u"\U0001F1E0-\U0001F1FF"  # флаги
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            "]+", flags=re.UNICODE)
        text = emoji_pattern.sub(r'', text)
        
        # 9. Удаляем строки с рекламными словами
        ad_words = [
            'подпишись', 'присоединяйся', 'подписывайся', 'переходи',
            'источник', 'реклама', 'промо', 'партнёрка', 'спонсор',
            'донат', 'поддержать', 'мы в max', 'сообщить новость',
            'читайте', 'смотрите', 'подробнее'
        ]
        
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line_lower = line.lower().strip()
            # Пропускаем строки, которые содержат рекламные слова
            if not any(word in line_lower for word in ad_words):
                cleaned_lines.append(line)
        
        text = '\n'.join(cleaned_lines)
        
        # 10. Удаляем слишком короткие строки (после очистки)
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            if len(line.strip()) > 3:
                cleaned_lines.append(line.strip())
        
        text = '\n'.join(cleaned_lines)
        
        # 11. Убираем лишние пробелы и пустые строки
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n+', '\n', text)
        
        text = text.strip()
        
        if text != original:
            logger.debug(f"Cleaned: {len(original)} -> {len(text)} chars")
        
        return text