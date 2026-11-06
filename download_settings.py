"""Local export destination. Paths are selected explicitly, never taken from a page."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from storage import DATA, ROOT, read, save

CONFIG = DATA / 'download-settings.json'
PICK_LOCK = threading.Lock()


def folder_path(value):
    path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        raise ValueError('请输入完整的本机文件夹路径')
    path = path.resolve()
    if path.exists() and not path.is_dir():
        raise ValueError('保存位置必须是文件夹，不能是文件')
    return path


def settings():
    config = read(CONFIG, {})
    return {'folder': str(folder_path(config.get('folder') or str(DATA / 'rag_exports'))),
            'mode': config.get('mode', 'browser')}


def update(config):
    mode = config.get('mode', 'folder')
    if mode not in ('browser', 'folder'):
        raise ValueError('不支持的保存方式')
    result = {'folder': str(folder_path(config.get('folder', settings()['folder']))), 'mode': mode}
    save(CONFIG, result)
    return result


def pick_folder():
    if not PICK_LOCK.acquire(blocking=False):
        raise ValueError('文件夹选择窗口已经打开，请先处理该窗口')
    try:
        completed = subprocess.run([sys.executable, str(ROOT / 'choose_download_folder.py'), settings()['folder']],
            capture_output=True, text=True, encoding='utf-8', timeout=180,
            env={**os.environ, 'PYTHONUTF8': '1'},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if completed.returncode:
            raise ValueError('未能打开本机文件夹选择窗口，可在网页直接粘贴路径并应用')
        selected = json.loads(completed.stdout).get('folder')
        return update({'folder': selected, 'mode': 'folder'}) if selected else {**settings(), 'cancelled': True}
    except subprocess.TimeoutExpired:
        raise ValueError('选择文件夹已超时，可重新选择或直接粘贴路径') from None
    finally:
        PICK_LOCK.release()


def open_folder(value):
    path = folder_path(value)
    if not path.is_dir():
        raise ValueError('该目录尚不存在，请先保存资料')
    if os.name != 'nt':
        raise ValueError('请复制页面显示的路径，在文件管理器中打开')
    os.startfile(str(path))
    return {'ok': True, 'folder': str(path)}
