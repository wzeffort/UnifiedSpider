import hashlib
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
SESSIONS = ROOT / 'sessions'
PROFILES = ROOT / 'browser_profiles'
DATA.mkdir(exist_ok=True)
SESSIONS.mkdir(exist_ok=True)


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def session_path(url):
    origin = urlsplit(url)
    key = hashlib.sha256(f'{origin.scheme}://{origin.netloc}'.encode()).hexdigest()
    return SESSIONS / (key + '.json')


def profile_path(url):
    return PROFILES / session_path(url).stem
