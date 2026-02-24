import json
from pathlib import Path

from django.conf import settings

from .base import BaseSource


class JsonFileSource(BaseSource):
    def __init__(self, path=None):
        self.path = Path(path) if path else settings.BASE_DIR / 'erp_data.json'

    def load(self) -> list[dict]:
        with open(self.path, 'r', encoding='utf-8') as f:
            return json.load(f)
