import hashlib
import sqlite3
import threading
import time

from .config import CACHE_DB, CACHE_TTL

_db = None
_lock = threading.Lock()  # 웹 UI는 여러 스레드에서 호출하므로 연결 공유 시 잠금


def _cache():
    global _db
    if _db is None:
        _db = sqlite3.connect(CACHE_DB, check_same_thread=False)
        _db.execute("CREATE TABLE IF NOT EXISTS qa (k TEXT PRIMARY KEY, answer TEXT, ts REAL)")
    return _db


def _key(q: str) -> str:
    return hashlib.sha256(" ".join(q.lower().split()).encode()).hexdigest()


def cache_get(q):
    with _lock:
        row = _cache().execute(
            "SELECT answer FROM qa WHERE k=? AND ts>?", (_key(q), time.time() - CACHE_TTL)
        ).fetchone()
    return row[0] if row else None


def cache_put(q, a):
    with _lock:
        db = _cache()
        db.execute("INSERT OR REPLACE INTO qa VALUES (?,?,?)", (_key(q), a, time.time()))
        db.commit()
