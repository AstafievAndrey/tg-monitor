import json
import os
from typing import Set, Dict, Any
from datetime import datetime, timedelta

class Database:
    """Простое хранение обработанных постов в JSON файле"""
    
    def __init__(self, db_path: str = 'processed_posts.json'):
        self.db_path = db_path
        self.processed_posts: Set[str] = set()
        self.posts_data: Dict[str, Any] = {}
        self.load()
    
    def load(self):
        """Загружает данные из файла"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.processed_posts = set(data.get('posts', []))
                    self.posts_data = data.get('data', {})
            except Exception:
                pass
    
    def save(self):
        """Сохраняет данные в файл"""
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'posts': list(self.processed_posts),
                    'data': self.posts_data
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    def is_processed(self, post_id: str) -> bool:
        """Проверяет, обработан ли пост"""
        return post_id in self.processed_posts
    
    def add_processed(self, post_id: str, data: Dict = None):
        """Добавляет пост в обработанные"""
        self.processed_posts.add(post_id)
        if data:
            self.posts_data[post_id] = {
                'data': data,
                'timestamp': datetime.now().isoformat()
            }
        self.save()
    
    def clean_old(self, days: int = 7):
        """Очищает старые записи (старше N дней)"""
        cutoff = datetime.now() - timedelta(days=days)
        to_remove = []
        
        for post_id, data in self.posts_data.items():
            if 'timestamp' in data:
                try:
                    ts = datetime.fromisoformat(data['timestamp'])
                    if ts < cutoff:
                        to_remove.append(post_id)
                except Exception:
                    pass
        
        for post_id in to_remove:
            self.processed_posts.discard(post_id)
            del self.posts_data[post_id]
        
        if to_remove:
            self.save()

# Глобальный экземпляр
db = Database()