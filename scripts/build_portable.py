"""Build an allowlisted offline Windows distribution; never copy user state."""
import json
import hashlib
import shutil
import time
import zipfile
from pathlib import Path
import conda_pack

PROJECT = Path(__file__).resolve().parent.parent
ROOT = PROJECT / 'app'
OUTPUT = PROJECT.parent / 'releases'
OUTPUT.mkdir(exist_ok=True)
stamp = time.strftime('%Y%m%d-%H%M%S')
stage = OUTPUT / ('WebCollector-Windows-x64-' + stamp)
stage.mkdir()
(stage / 'app').mkdir()
files = [p.name for p in ROOT.glob('*.py')] + ['index.html', 'browser_bridge.js', 'author_batch_ui.js']
for name in files:
    shutil.copy2(ROOT / name, stage / 'app' / name)
for name in ('browser-extension', 'CookieEditor-Collector'):
    shutil.copytree(ROOT / name, stage / 'app' / name, ignore=shutil.ignore_patterns('__pycache__', 'node_modules', '.git'))
shutil.copy2(PROJECT / 'config' / 'requirements.txt', stage / 'app' / 'requirements.txt')
shutil.copy2(PROJECT / 'scripts' / 'portable-start.bat', stage / '启动.bat')
shutil.copy2(PROJECT / 'scripts' / 'portable-start.bat', stage / 'start.bat')
shutil.copy2(PROJECT / 'scripts' / 'bootstrap.ps1', stage / 'bootstrap.ps1')
shutil.copy2(PROJECT / 'docs' / 'portable-readme.txt', stage / '使用说明.txt')
print('Packing Python environment...', flush=True)
env = conda_pack.CondaEnv.from_prefix(r'D:\Anaconda\envs\spider-crawl4ai', ignore_editable_packages=True)
env = env.exclude('Lib/site-packages/__editable__*').exclude('Lib/site-packages/crawl4ai-*.dist-info/direct_url.json')
env.pack(output=str(stage / 'runtime.zip'), format='zip', compress_level=2)
# The development install points outside the environment. Vendor its actual
# source instead of shipping a .pth that points to the developer's drive.
with zipfile.ZipFile(stage / 'runtime.zip', 'a', zipfile.ZIP_DEFLATED, compresslevel=2) as runtime:
    for path in (PROJECT.parent / 'Crawl4AI' / 'crawl4ai').rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            runtime.write(path, 'Lib/site-packages/crawl4ai/' + path.relative_to(PROJECT.parent / 'Crawl4AI' / 'crawl4ai').as_posix())
browser_root = Path(r'C:\Users\Administrator\AppData\Local\ms-playwright')
for name in ('chromium-1234', 'chromium_headless_shell-1234', 'ffmpeg-1011', 'winldd-1007'):
    shutil.copytree(browser_root / name, stage / 'browsers' / name)
manifest = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in stage.rglob('*') if p.is_file()}
(stage / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
archive = stage.with_suffix('.zip')
print('Building delivery ZIP...', flush=True)
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=2) as bundle:
    for path in stage.rglob('*'):
        if path.is_file():
            bundle.write(path, str(Path(stage.name) / path.relative_to(stage)),
                         compress_type=zipfile.ZIP_STORED if path.name == 'runtime.zip' else zipfile.ZIP_DEFLATED)
print(json.dumps({'folder': str(stage), 'zip': str(archive), 'bytes': archive.stat().st_size}), flush=True)
