"""Persistent music library and reversible file operations (no GUI dependency)."""
import json
import random
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

STYLES = ('other', 'rockPOP', 'blues', 'country', 'chinese', 'punk', 'hardrock', 'jPop', 'solo', 'metal')
EXTENSIONS = {'.mp3', '.flac', '.wav', '.ogg', '.opus', '.m4a', '.aac', '.wma'}


def unique_path(path):
    path = Path(path)
    candidate = path
    n = 1
    while candidate.exists():
        candidate = path.with_name(f'{path.stem} ({n}){path.suffix}')
        n += 1
    return candidate


class Library:
    def __init__(self, database):
        self.db = sqlite3.connect(str(database))
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS trash (
                id INTEGER PRIMARY KEY AUTOINCREMENT, root TEXT NOT NULL,
                original TEXT NOT NULL, stored TEXT NOT NULL);
        ''')
        self.root = None
        self.tracks = []
        self.queue = []
        self.history = []
        self.random = random.Random(time.time_ns())

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    def open(self, folder):
        root = Path(folder).resolve()
        if not root.is_dir():
            raise FileNotFoundError('Source folder not found')
        self.root = root
        self.scan()
        self.history = []
        saved_queue = self.get('queue:' + str(root))
        self.queue = [p for p in saved_queue if p in self.tracks] if saved_queue is not None else self.tracks.copy()
        if saved_queue is None:
            self.random.shuffle(self.queue)
        self.set('root', str(root))
        return self.get('current:' + str(root))

    def scan(self):
        import os
        tracks = []
        for folder, dirs, files in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if d.lower() not in {'tmp_trash', 'classify'} and not Path(folder, d).is_symlink())
            tracks.extend(str(Path(folder, f)) for f in files if Path(f).suffix.lower() in EXTENSIONS and not f.startswith('.') and not Path(folder, f).is_symlink())
        self.tracks = sorted(tracks, key=str.casefold)

    def remember_queue(self):
        if self.root:
            self.set('queue:' + str(self.root), self.queue)

    def played(self, path):
        if not self.history or self.history[-1]['path'] != path or self.history[-1]['status'] != 'available':
            self.history.append({'path': path, 'status': 'available'})
        self.queue = [p for p in self.queue if p != path]
        self.remember_queue()
        self.set('current:' + str(self.root), path)

    def next(self, current, random_mode=False):
        if not self.tracks:
            return None
        if random_mode:
            self.queue = [p for p in self.queue if p in self.tracks]
            if not self.queue:
                self.queue = self.tracks.copy()
                self.random.shuffle(self.queue)
                if len(self.queue) > 1 and self.queue[0] == current:
                    self.queue[0], self.queue[1] = self.queue[1], self.queue[0]
            result = self.queue.pop(0)
            self.remember_queue()
            return result
        if current in self.tracks:
            return self.tracks[(self.tracks.index(current) + 1) % len(self.tracks)]
        return self.tracks[0]

    def forget(self, path, status):
        self.tracks = [p for p in self.tracks if p != path]
        self.queue = [p for p in self.queue if p != path]
        for item in self.history:
            if item['path'] == path:
                item['status'] = status
        self.remember_queue()

    def classify(self, path, style):
        if style not in STYLES:
            raise ValueError('Unknown category')
        target = self.root.parent / 'classify' / style
        target.mkdir(parents=True, exist_ok=True)
        dest = unique_path(target / Path(path).name)
        shutil.move(path, dest)
        self.forget(path, 'classified')
        return dest

    def delete(self, path):
        if path not in self.tracks:
            raise FileNotFoundError('Track unavailable')
        trash = self.root / 'tmp_trash'
        trash.mkdir(exist_ok=True)
        stored = trash / (uuid.uuid4().hex + Path(path).suffix)
        shutil.move(path, stored)
        try:
            with self.db:
                self.db.execute('INSERT INTO trash(root,original,stored) VALUES (?,?,?)', (str(self.root), path, str(stored)))
        except Exception:
            shutil.move(stored, path)
            raise
        self.forget(path, 'deleted')
        rows = self.db.execute('SELECT id,stored FROM trash WHERE root=? ORDER BY id DESC LIMIT -1 OFFSET 10', (str(self.root),)).fetchall()
        for ident, old in rows:
            Path(old).unlink(missing_ok=True)
            with self.db:
                self.db.execute('DELETE FROM trash WHERE id=?', (ident,))

    def restore(self):
        row = self.db.execute('SELECT id,original,stored FROM trash WHERE root=? ORDER BY id DESC LIMIT 1', (str(self.root),)).fetchone()
        if not row:
            return None
        ident, original, stored = row
        if not Path(stored).exists():
            with self.db:
                self.db.execute('DELETE FROM trash WHERE id=?', (ident,))
            raise FileNotFoundError('Trash file not found')
        target = unique_path(original)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(stored, target)
        try:
            with self.db:
                self.db.execute('DELETE FROM trash WHERE id=?', (ident,))
        except Exception:
            shutil.move(target, stored)
            raise
        self.scan()
        if str(target) in self.tracks and str(target) not in self.queue:
            self.queue.append(str(target))
        self.remember_queue()
        return target

    def close(self):
        self.db.close()
