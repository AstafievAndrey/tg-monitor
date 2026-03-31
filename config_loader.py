import json
import os
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

class ConfigLoader:
    """Загрузчик конфигурации из .env и JSON"""
    
    def __init__(self):
        # Загружаем чувствительные данные из .env
        self.api_id = int(os.getenv('API_ID', 0))
        self.api_hash = os.getenv('API_HASH', '')
        self.phone_number = os.getenv('PHONE_NUMBER', '')
        self.bot_token = os.getenv('BOT_TOKEN', '')
        
        # Загружаем основную конфигурацию
        config_path = os.getenv('CONFIG_PATH', 'config.json')
        self.json_config = self.load_json_config(config_path)
    
    def load_json_config(self, path: str) -> Dict[str, Any]:
        """Загружает JSON конфигурацию"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Файл конфигурации {path} не найден!")
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def parse_channel(self, channel: str):
        """Парсит ID канала или username"""
        if not channel:
            return None
        
        channel = channel.strip()
        
        if channel.startswith('https://t.me/'):
            channel = channel.replace('https://t.me/', '@')
        
        if channel.startswith('-100') or (channel.lstrip('-').isdigit()):
            return int(channel)
        
        return channel
    
    @property
    def draft_channel_id(self):
        return self.parse_channel(self.json_config['draft']['channel'])
    
    @property
    def check_interval(self) -> int:
        return self.json_config.get('check_interval', 10)
    
    @property
    def channels_config(self) -> List[Dict]:
        """Возвращает список каналов с распарсенными ID"""
        configs = []
        for channel in self.json_config.get('channels', []):
            configs.append({
                'name': channel['name'],
                'public_channel_id': self.parse_channel(channel['public_channel']),
                'public_channel': channel['public_channel'],
                'source_channels': [self.parse_channel(src) for src in channel.get('source_channels', [])],
                'hashtags': channel.get('hashtags', [])
            })
        return configs
    
    def get_channel_by_name(self, name: str) -> Optional[Dict]:
        """Получает конфигурацию канала по имени"""
        for channel in self.channels_config:
            if channel['name'] == name:
                return channel
        return None

# Создаем глобальный экземпляр
config = ConfigLoader()