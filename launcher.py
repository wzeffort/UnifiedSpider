import json
import importlib.util
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

url = 'http://127.0.0.1:18765'
try:
    with urllib.request.urlopen(url + '/health', timeout=2) as response:
        existing = json.load(response)
    if existing.get('app') != 'UnifiedSpider':
        raise RuntimeError('Port 18765 belongs to another application')
except (OSError, ValueError):
    missing = [name for name in ('fastapi', 'uvicorn', 'scrapy', 'crawl4ai', 'playwright', 'markdownify') if importlib.util.find_spec(name) is None]
    if missing:
        print('Missing dependencies: ' + ', '.join(missing))
        print('Run install.bat once, then start.bat. Startup does not install packages automatically.')
        sys.exit(1)
    sys.exit(subprocess.call([sys.executable, str(Path(__file__).with_name('app.py'))]))
else:
    print('UnifiedSpider is already running. Opening browser.')
    webbrowser.open(url)
