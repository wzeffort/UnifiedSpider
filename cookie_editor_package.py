"""Package only distributable extension source; never include browser profiles."""
import io
import json
import zipfile
from storage import ROOT


def addon_root():
    bundled = ROOT / 'CookieEditor-Collector'
    return bundled if bundled.is_dir() else ROOT.parent / 'CookieEditor-Collector'


def package():
    addon = addon_root()
    root_names = ('manifest.json', 'manifest.edge.json', 'manifest.chrome.json',
                  'cookie-editor.js', 'collector-background.js', 'collector-content.js',
                  'collector-authorize.html', 'collector-authorize.js', 'LICENSE',
                  'README.md', 'COLLECTOR-README.md', 'package.json', 'package-lock.json',
                  'Gruntfile.cjs', 'build.ps1', 'eslint.config.mjs', '.prettierrc.json')
    files = [addon / name for name in root_names if (addon / name).is_file()]
    for name in ('interface', 'icons', 'test'):
        files.extend(p for p in (addon / name).rglob('*') if p.is_file())
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_symlink() or not path.resolve().is_relative_to(addon.resolve()):
                raise ValueError('扩展资源路径不正确')
            archive.write(path, 'CookieEditor-Collector/' + path.relative_to(addon).as_posix())
    version = json.loads((addon / 'manifest.json').read_text(encoding='utf-8'))['version']
    return output.getvalue(), f'CookieEditor-Collector-{version}.zip'
