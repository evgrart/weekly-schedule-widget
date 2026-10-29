"""User configuration with no embedded accounts or calendar URLs."""
import json
import os
from urllib.parse import urlsplit

from app_paths import DATA_ROOT

CONFIG = DATA_ROOT/'config.json'


def load_config():
    try:
        stored = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
        if not isinstance(stored, dict):
            stored = {}
    except (OSError, ValueError):
        stored = {}
    config = {'feed_url':'', 'refresh_seconds':120, 'topmost':False,
              'autostart':False, 'desktop_mode':False, 'shad_enabled':True}
    config.update(stored)
    try:
        config['refresh_seconds'] = max(60, int(config['refresh_seconds']))
    except (TypeError, ValueError):
        config['refresh_seconds'] = 120
    return config


def save_config(config):
    temporary = CONFIG.with_suffix('.tmp')
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, CONFIG)


def valid_feed(url):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'calendar.google.com'
            and not parsed.username and not parsed.password and parsed.path.endswith('.ics'))
