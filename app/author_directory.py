"""Readable archive names with stable, explicit account identity."""
import hashlib
import re
from storage import read, save


def clean_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value or '').strip().lstrip('@'))
    return value.strip(' .')[:80]


def resolve_directory(root, source, identity):
    root.mkdir(parents=True, exist_ok=True)
    legacy = root / identity
    existing = []
    for path in root.iterdir():
        if path.is_dir() and not path.is_symlink():
            marker = read(path / 'export.json', {})
            if marker.get('author_key') == identity or path == legacy:
                existing.append(path)
    if len(existing) > 1:
        raise ValueError('同一作者存在多个导出目录，请先检查，未覆盖任何目录')
    current = existing[0] if existing else None
    name = clean_name(source.get('name'))
    # Keep a named directory stable across account nickname changes.
    if current and current != legacy:
        return current
    prefix = {'xueqiu': '雪球', 'wechat': '微信公众号'}.get(source['platform'], source['platform'])
    target = root / (prefix + '_' + name) if name else legacy
    if target != current and target.exists():
        target = root / (prefix + '_' + name + '_' + hashlib.sha256(identity.encode()).hexdigest()[:8])
        if target.exists():
            raise ValueError('作者目录名称冲突，未覆盖已有文件')
    if target.is_symlink() or (current and current.is_symlink()):
        raise ValueError('作者目录不能是符号链接')
    if current and current != target:
        current.rename(target)
        marker = read(target / 'export.json', {})
        marker.update(author_key=identity, author_name=source.get('name'), folder=str(target),
                      documents_file=str(target / 'documents.jsonl'))
        save(target / 'export.json', marker)
    target.mkdir(parents=True, exist_ok=True)
    return target
