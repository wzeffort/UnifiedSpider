"""Indexed, transactional per-article storage with read-only legacy fallback."""
import json
import sqlite3
from collections import OrderedDict
import threading
from storage import read

_METRICS = OrderedDict()
_METRICS_LOCK = threading.Lock()


def contains_any(folder, candidates):
    """Point lookups use the URL primary key, without reading article bodies."""
    if not (folder / 'articles.sqlite3').exists():
        return bool(urls(folder).intersection(candidates))
    db = connect(folder)
    try:
        return any(db.execute('SELECT 1 FROM articles WHERE url=?', (url,)).fetchone() for url in candidates)
    finally:
        db.close()


def image_counts(folder):
    def fingerprint():
        paths = [folder/name for name in ('articles.sqlite3', 'articles.sqlite3-wal', 'result.json')]
        return tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in paths)
    key = str(folder.resolve())
    stamp = fingerprint()
    with _METRICS_LOCK:
        cached = _METRICS.get(key)
        if cached and cached[0] == stamp:
            return dict(cached[1])
    c = dict(total=0, complete=0, pending=0, failed=0, downloaded=0, pages=0, pagesWithImages=0, pagesComplete=0)
    if (folder/'articles.sqlite3').exists():
        db = connect(folder)
        try:
            # Transfer only image metadata from SQLite, never article text/HTML.
            images_by_page = [json.loads(row[0] or '[]') for row in db.execute("SELECT json_extract(payload, '$.images') FROM articles")]
        finally:
            db.close()
    else:
        images_by_page = [p.get('images', []) for p in read(folder/'result.json', {}).get('pages', [])]
    for images in images_by_page:
        c['pages'] += 1
        if images:
            c['pagesWithImages'] += 1
            if all(i.get('ocr') and not i.get('error') for i in images):
                c['pagesComplete'] += 1
        for item in images:
            c['total'] += 1
            c['downloaded'] += bool(item.get('file'))
            c['failed' if item.get('error') else 'complete' if item.get('ocr') else 'pending'] += 1
    with _METRICS_LOCK:
        if stamp == fingerprint():
            _METRICS[key] = (stamp, c)
            _METRICS.move_to_end(key)
            while len(_METRICS) > 128:
                _METRICS.popitem(last=False)
    return dict(c)


def connect(folder):
    db = sqlite3.connect(folder / 'articles.sqlite3', timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS articles(url TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS failures(payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS migration(done INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS properties(key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    if not db.execute('SELECT 1 FROM migration').fetchone():
        old = read(folder / 'result.json', {})
        for page in old.get('pages', []):
            db.execute('INSERT OR IGNORE INTO articles VALUES (?,?)', (page['url'], json.dumps(page, ensure_ascii=False)))
        for failure in old.get('failures', []):
            db.execute('INSERT INTO failures VALUES (?)', (json.dumps(failure, ensure_ascii=False),))
        generated_rows = [{'来源网址': p['url'], '标题': p['title'], '正文': p['text']} for p in old.get('pages', [])]
        if old.get('rows') and old['rows'] != generated_rows:
            db.execute('INSERT OR IGNORE INTO properties VALUES (?,?)', ('rows', json.dumps(old['rows'], ensure_ascii=False)))
        db.execute('INSERT INTO migration VALUES (1)')
        db.commit()
    return db


def put(folder, page, replace=False):
    db = connect(folder)
    try:
        with db:
            db.execute('INSERT INTO articles VALUES (?,?) ON CONFLICT(url) DO UPDATE SET payload=excluded.payload' if replace else 'INSERT OR IGNORE INTO articles VALUES (?,?)', (page['url'], json.dumps(page, ensure_ascii=False)))
    finally:
        db.close()


def fail(folder, failure):
    db = connect(folder)
    try:
        with db:
            db.execute('INSERT INTO failures VALUES (?)', (json.dumps(failure, ensure_ascii=False),))
    finally:
        db.close()


def count(folder):
    if not (folder / 'articles.sqlite3').exists():
        return len(read(folder / 'result.json', {}).get('pages', []))
    db = connect(folder)
    try:
        return db.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
    finally:
        db.close()


def result(folder):
    if not (folder / 'articles.sqlite3').exists():
        return read(folder / 'result.json', {'pages': [], 'rows': [], 'failures': []})
    db = connect(folder)
    try:
        pages = [json.loads(row[0]) for row in db.execute('SELECT payload FROM articles ORDER BY rowid')]
        failures = [json.loads(row[0]) for row in db.execute('SELECT payload FROM failures')]
        custom = db.execute("SELECT payload FROM properties WHERE key='rows'").fetchone()
        return {'pages': pages, 'rows': json.loads(custom[0]) if custom else [{'来源网址': p['url'], '标题': p['title'], '正文': p['text']} for p in pages], 'failures': failures}
    finally:
        db.close()


def save_rows(folder, rows):
    db = connect(folder)
    try:
        with db:
            db.execute('INSERT OR REPLACE INTO properties VALUES (?,?)', ('rows', json.dumps(rows, ensure_ascii=False)))
    finally:
        db.close()


def urls(folder):
    if not (folder / 'articles.sqlite3').exists():
        return {p['url'] for p in read(folder / 'result.json', {}).get('pages', [])}
    db = connect(folder)
    try:
        return {row[0] for row in db.execute('SELECT url FROM articles')}
    finally:
        db.close()


def get(folder, url):
    if not (folder / 'articles.sqlite3').exists():
        return next((p for p in result(folder)['pages'] if p['url'] == url), None)
    db = connect(folder)
    try:
        row = db.execute('SELECT payload FROM articles WHERE url=?', (url,)).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        db.close()
