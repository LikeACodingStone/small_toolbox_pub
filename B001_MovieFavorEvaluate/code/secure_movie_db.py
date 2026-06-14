import argparse
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import uuid
from datetime import UTC, datetime, timedelta
from getpass import getpass
from pathlib import Path

from crypto_utils import aes_gcm_decrypt, aes_gcm_encrypt
from movie_library import DATA_DIR, compact_title, read_json, title_aliases, write_json

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = DATA_DIR / "movie_favor_secure.db"
SESSION_PATH = DATA_DIR / ".movie_favor_db_session.json"
POSITIVE_JSON = DATA_DIR / "my_pos_movies.json"
NEGATIVE_JSON = DATA_DIR / "my_neg_movies.json"
FEEDBACK_JSON = DATA_DIR / "feedback.json"
TASTE_PROFILE_JSON = DATA_DIR / "taste_profile.json"
SESSION_DAYS = 3


def now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


def b64(data):
    return base64.b64encode(data).decode("ascii")


def unb64(text):
    return base64.b64decode(text.encode("ascii"))


def derive_secret(passphrase, salt):
    material = hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        260_000,
        dklen=64,
    )
    return {
        "enc": b64(material[:32]),
        "hmac": b64(material[32:]),
    }


def new_session(passphrase):
    salt = os.urandom(16)
    expires_at = utc_now() + timedelta(days=SESSION_DAYS)
    session = {
        "version": 1,
        "created_at": utc_now().isoformat(timespec="seconds") + "Z",
        "expires_at": expires_at.isoformat(timespec="seconds") + "Z",
        "salt": b64(salt),
        "secret": aes_gcm_encrypt(json.dumps(derive_secret(passphrase, salt)), passphrase),
    }
    write_json(SESSION_PATH, session)
    return session


def load_session(passphrase=None, create=True):
    session = read_json(SESSION_PATH, None)
    if session:
        try:
            expires_at = datetime.fromisoformat(session["expires_at"].replace("Z", ""))
            if utc_now() < expires_at:
                if passphrase is None:
                    passphrase = password_from_env_or_prompt()
                secret_text = aes_gcm_decrypt(session["secret"], passphrase)
                return json.loads(secret_text)
        except Exception:
            pass

    if not create:
        raise RuntimeError("No valid database session found.")
    if passphrase is None:
        passphrase = password_from_env_or_prompt()
    session = new_session(passphrase)
    return json.loads(aes_gcm_decrypt(session["secret"], passphrase))


def password_from_env_or_prompt():
    for name in ("MOVIE_DB_PASSWORD", "MOVIE_TMDB_KEY_PASSWORD", "TMDB_API_KEY_PASSWORD"):
        value = os.environ.get(name)
        if value:
            return value
    return getpass("请输入数据库 session 口令：")


def enc_json(value, keys):
    text = json.dumps(value, ensure_ascii=False)
    payload = aes_gcm_encrypt(text, keys["enc"])
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def dec_json(value, keys, default=None):
    if not value:
        return default
    payload = json.loads(value)
    return json.loads(aes_gcm_decrypt(payload, keys["enc"]))


def title_hmac(title, keys):
    normalized = compact_title(str(title))
    digest = hmac.new(unb64(keys["hmac"]), normalized.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def connect(db_path=DB_PATH):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn):
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS movies (
          movie_id TEXT PRIMARY KEY,
          title_enc TEXT NOT NULL,
          title_hmac TEXT UNIQUE NOT NULL,
          tmdb_id_enc TEXT,
          sentiment TEXT NOT NULL,
          source_type TEXT NOT NULL,
          source_file TEXT,
          target_score REAL,
          core_reason_enc TEXT,
          payload_enc TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS aliases (
          alias_hmac TEXT PRIMARY KEY,
          movie_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(movie_id) REFERENCES movies(movie_id)
        );

        CREATE TABLE IF NOT EXISTS feedback (
          feedback_id TEXT PRIMARY KEY,
          movie_id TEXT,
          title_hmac TEXT,
          actual_score REAL,
          model_score REAL,
          payload_enc TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(movie_id) REFERENCES movies(movie_id)
        );

        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value_enc TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS json_files (
          file_name TEXT PRIMARY KEY,
          content_enc TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def upsert_movie(conn, keys, item, sentiment, source_type, source_file):
    title = str(item.get("title", "")).strip()
    if not title:
        return None

    th = title_hmac(title, keys)
    existing = conn.execute("SELECT movie_id FROM movies WHERE title_hmac = ?", (th,)).fetchone()
    movie_id = existing["movie_id"] if existing else f"m_{uuid.uuid4().hex}"
    timestamp = now_text()
    target_score = item.get("target_score")
    if target_score is None:
        target_score = 100 if sentiment == "positive" else 40

    payload = dict(item)
    conn.execute(
        """
        INSERT INTO movies (
          movie_id, title_enc, title_hmac, tmdb_id_enc, sentiment, source_type,
          source_file, target_score, core_reason_enc, payload_enc, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(title_hmac) DO UPDATE SET
          title_enc = excluded.title_enc,
          tmdb_id_enc = excluded.tmdb_id_enc,
          sentiment = excluded.sentiment,
          source_type = excluded.source_type,
          source_file = excluded.source_file,
          target_score = excluded.target_score,
          core_reason_enc = excluded.core_reason_enc,
          payload_enc = excluded.payload_enc,
          updated_at = excluded.updated_at
        """,
        (
            movie_id,
            enc_json(title, keys),
            th,
            enc_json(item.get("tmdb_id"), keys) if item.get("tmdb_id") is not None else None,
            sentiment,
            source_type,
            source_file,
            float(target_score),
            enc_json(item.get("core_reason") or item.get("reason") or "", keys),
            enc_json(payload, keys),
            timestamp,
            timestamp,
        ),
    )

    for alias in title_aliases(title):
        alias_digest = hmac.new(unb64(keys["hmac"]), alias.encode("utf-8"), hashlib.sha256).hexdigest()
        conn.execute(
            """
            INSERT OR REPLACE INTO aliases (alias_hmac, movie_id, created_at)
            VALUES (?, ?, ?)
            """,
            (alias_digest, movie_id, timestamp),
        )
    return movie_id


def import_json_to_db(db_path=DB_PATH, passphrase=None):
    keys = load_session(passphrase)
    conn = connect(db_path)
    try:
        init_schema(conn)
        counts = {"positive": 0, "negative": 0, "feedback": 0, "settings": 0, "json_files": 0}
        conn.execute("DELETE FROM aliases")
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM movies")

        for json_path in sorted(DATA_DIR.glob("*.json")):
            content = read_json(json_path, None)
            if content is None:
                continue
            conn.execute(
                """
                INSERT INTO json_files (file_name, content_enc, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(file_name) DO UPDATE SET
                  content_enc = excluded.content_enc,
                  updated_at = excluded.updated_at
                """,
                (json_path.name, enc_json(content, keys), now_text()),
            )
            counts["json_files"] += 1

        for item in read_json(POSITIVE_JSON, []):
            if isinstance(item, dict) and upsert_movie(conn, keys, item, "positive", "json", POSITIVE_JSON.name):
                counts["positive"] += 1
        for item in read_json(NEGATIVE_JSON, []):
            if isinstance(item, dict) and upsert_movie(conn, keys, item, "negative", "json", NEGATIVE_JSON.name):
                counts["negative"] += 1

        for item in read_json(FEEDBACK_JSON, []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("query") or "").strip()
            feedback_id = f"f_{uuid.uuid4().hex}"
            movie_id = None
            th = title_hmac(title, keys) if title else None
            if th:
                existing = conn.execute("SELECT movie_id FROM movies WHERE title_hmac = ?", (th,)).fetchone()
                movie_id = existing["movie_id"] if existing else None
            conn.execute(
                """
                INSERT INTO feedback (
                  feedback_id, movie_id, title_hmac, actual_score, model_score, payload_enc, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    movie_id,
                    th,
                    item.get("actual_score"),
                    item.get("predicted_score"),
                    enc_json(item, keys),
                    item.get("created_at") or now_text(),
                ),
            )
            counts["feedback"] += 1

        taste_profile = read_json(TASTE_PROFILE_JSON, {})
        conn.execute(
            """
            INSERT INTO settings (key, value_enc, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_enc = excluded.value_enc, updated_at = excluded.updated_at
            """,
            ("taste_profile", enc_json(taste_profile, keys), now_text()),
        )
        counts["settings"] += 1
        conn.commit()
        return counts
    finally:
        conn.close()


def export_db_to_json(db_path=DB_PATH, passphrase=None, overwrite=False):
    keys = load_session(passphrase)
    conn = connect(db_path)
    try:
        init_schema(conn)
        positives = []
        negatives = []
        exact_json_files = {}
        for row in conn.execute("SELECT * FROM movies ORDER BY created_at, movie_id"):
            payload = dec_json(row["payload_enc"], keys, {})
            payload["title"] = dec_json(row["title_enc"], keys, payload.get("title"))
            payload["target_score"] = row["target_score"]
            if row["sentiment"] == "positive":
                positives.append(payload)
            elif row["sentiment"] == "negative":
                negatives.append(payload)

        feedback = [
            dec_json(row["payload_enc"], keys, {})
            for row in conn.execute("SELECT * FROM feedback ORDER BY created_at, feedback_id")
        ]
        settings_row = conn.execute("SELECT value_enc FROM settings WHERE key = ?", ("taste_profile",)).fetchone()
        for row in conn.execute("SELECT file_name, content_enc FROM json_files ORDER BY file_name"):
            exact_json_files[row["file_name"]] = dec_json(row["content_enc"], keys, None)

        if overwrite:
            if exact_json_files:
                for file_name, content in exact_json_files.items():
                    write_json(DATA_DIR / file_name, content)
            else:
                write_json(POSITIVE_JSON, positives)
                write_json(NEGATIVE_JSON, negatives)
                write_json(FEEDBACK_JSON, feedback)
                if settings_row:
                    write_json(TASTE_PROFILE_JSON, dec_json(settings_row["value_enc"], keys, {}))

        return {
            "normalized_positive_unique": len(positives),
            "normalized_negative_unique": len(negatives),
            "feedback": len(feedback),
            "taste_profile": bool(settings_row),
            "exact_json_files": len(exact_json_files),
        }
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Convert plain JSON data to/from encrypted SQLite storage.")
    parser.add_argument("command", choices=["init-session", "import-json", "export-json"])
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--overwrite", action="store_true", help="For export-json, overwrite data/*.json with decrypted JSON.")
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.command == "init-session":
        load_session(create=True)
        print(f"database session ready: {SESSION_PATH}")
    elif args.command == "import-json":
        counts = import_json_to_db(db_path)
        print(json.dumps({"db": str(db_path), "imported": counts}, ensure_ascii=False, indent=2))
    elif args.command == "export-json":
        counts = export_db_to_json(db_path, overwrite=args.overwrite)
        print(json.dumps({"db": str(db_path), "exported": counts, "overwrite": args.overwrite}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
