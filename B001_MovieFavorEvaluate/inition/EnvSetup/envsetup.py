import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = ROOT / "code"
DATA_DIR = ROOT / "data"
INITION_DIR = ROOT / "inition"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import evaluate
from crypto_utils import aes_gcm_encrypt
from movie_library import compact_title, read_json, write_json
from secure_movie_db import import_json_to_db, load_session

POSITIVE_TXT = INITION_DIR / "positive.txt"
NEGTIVE_TXT = INITION_DIR / "negtive.txt"
RULES_TXT = INITION_DIR / "rules.txt"
TMDB_KEY_TXT = INITION_DIR / "tmdb_key.txt"
POSITIVE_JSON = DATA_DIR / "my_pos_movies.json"
NEGATIVE_JSON = DATA_DIR / "my_neg_movies.json"
TASTE_PROFILE_JSON = DATA_DIR / "taste_profile.json"
TMDB_KEY_ENC_JSON = DATA_DIR / "tmdb_api_key.enc.json"


def configure_utf8_output():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_utf8_output()


def parse_list_file(path):
    if not path.exists():
        return []
    titles = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        text = re.sub(r"^\s*[-*]\s*", "", text).strip()
        if text:
            titles.append(text)
    return titles


def write_remaining_list(path, remaining):
    lines = [f"- {title}" for title in remaining]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def parse_tmdb_key_file(path):
    if not path.exists():
        return None, None
    api_key = None
    password = None
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        if ":" in text:
            key, value = text.split(":", 1)
        elif "：" in text:
            key, value = text.split("：", 1)
        else:
            continue
        label = key.strip().lower()
        value = value.strip()
        if "key" in label:
            api_key = value
        elif "password" in label or "口令" in label or "密码" in label:
            password = value
    return api_key, password


def ensure_tmdb_key():
    api_key, password = parse_tmdb_key_file(TMDB_KEY_TXT)
    if api_key and password and not TMDB_KEY_ENC_JSON.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        write_json(TMDB_KEY_ENC_JSON, aes_gcm_encrypt(api_key, password))
        print(f"encrypted TMDb key written: {TMDB_KEY_ENC_JSON}")
    return password


def load_existing_aliases(path):
    aliases = set()
    data = read_json(path, [])
    if not isinstance(data, list):
        return aliases
    for item in data:
        if isinstance(item, dict) and item.get("title"):
            aliases.add(compact_title(item["title"]))
    return aliases


def movie_from_tmdb(title, sentiment):
    info = evaluate.get_movie_from_tmdb(title)
    resolved_title = info.get("title") if info else title
    genres = ", ".join(info.get("genres") or []) if info else ""
    directors = ", ".join(info.get("directors") or []) if info else ""
    if sentiment == "positive":
        reason = f"初始化正向样本。TMDb 类型: {genres or '未知'}；导演: {directors or '未知'}。"
        return {
            "title": resolved_title,
            "score": 100,
            "target_score": 100,
            "reason": reason,
            "core_reason": f"核心肯定点：{reason}",
            "tmdb_id": info.get("tmdb_id") if info else None,
        }
    reason = f"初始化反向样本，说明它存在你接受不了的表达或题材风险。TMDb 类型: {genres or '未知'}；导演: {directors or '未知'}。"
    return {
        "title": resolved_title,
        "score": 40,
        "target_score": 40,
        "reason": reason,
        "core_reason": f"核心否定点：{reason}",
        "tmdb_id": info.get("tmdb_id") if info else None,
    }


def append_new_movies(txt_path, json_path, sentiment):
    titles = parse_list_file(txt_path)
    if not titles:
        return 0

    movies = read_json(json_path, [])
    if not isinstance(movies, list):
        movies = []

    existing = load_existing_aliases(json_path)
    remaining = []
    added = 0
    for title in titles:
        alias = compact_title(title)
        if not alias or alias in existing:
            continue
        try:
            item = movie_from_tmdb(title, sentiment)
        except Exception as exc:
            print(f"failed to enrich {title}: {exc}")
            remaining.append(title)
            continue
        movies.append(item)
        existing.add(alias)
        added += 1

    write_json(json_path, movies)
    write_remaining_list(txt_path, remaining)
    return added


def build_taste_profile_from_rules():
    if not RULES_TXT.exists():
        return False
    rules = RULES_TXT.read_text(encoding="utf-8").strip()
    if not rules:
        return False
    profile = read_json(TASTE_PROFILE_JSON, evaluate.DEFAULT_TASTE_PROFILE)
    profile = evaluate.merge_dict(evaluate.DEFAULT_TASTE_PROFILE, profile)
    profile["template_rules_text"] = rules
    profile.setdefault("learned_core_features", {}).setdefault("positive", [])
    profile.setdefault("learned_core_features", {}).setdefault("negative", [])
    if not any(item.get("name") == "Initialization Rules" for item in profile["learned_core_features"]["positive"]):
        profile["learned_core_features"]["positive"].append(
            {
                "name": "Initialization Rules",
                "signal": rules,
            }
        )
    write_json(TASTE_PROFILE_JSON, profile)
    return True


def main():
    parser = argparse.ArgumentParser(description="Initialize template data from inition/*.txt into JSON and encrypted DB.")
    parser.add_argument("--skip-db", action="store_true")
    parser.add_argument("--skip-tmdb-key", action="store_true")
    args = parser.parse_args()

    password = None if args.skip_tmdb_key else ensure_tmdb_key()
    if password:
        os.environ.setdefault("MOVIE_TMDB_KEY_PASSWORD", password)
        os.environ.setdefault("MOVIE_DB_PASSWORD", password)

    if not evaluate.TMDB_API_KEY:
        evaluate.TMDB_API_KEY = evaluate.load_tmdb_api_key()

    pos_added = append_new_movies(POSITIVE_TXT, POSITIVE_JSON, "positive")
    neg_added = append_new_movies(NEGTIVE_TXT, NEGATIVE_JSON, "negative")
    rules_updated = build_taste_profile_from_rules()
    print(json.dumps({"positive_added": pos_added, "negative_added": neg_added, "rules_updated": rules_updated}, ensure_ascii=False, indent=2))

    if not args.skip_db:
        load_session(password)
        counts = import_json_to_db(passphrase=password)
        print(json.dumps({"db_imported": counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
