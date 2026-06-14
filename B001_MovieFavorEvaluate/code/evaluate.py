import json
import math
import os
import re
import sys
import ctypes
from base64 import b64decode, b64encode
from ctypes import wintypes
from datetime import UTC, datetime, timedelta
from getpass import getpass
from pathlib import Path

import ollama
import requests

from crypto_utils import aes_gcm_decrypt
from movie_library import DATA_DIR, iter_movies_details, read_json, title_aliases, write_json
from sync_movies import sync_missing_movies_test_file


def configure_utf8_output():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_utf8_output()

# ==================== 配置区 ====================
MODEL_NAME = "qwen2.5:7b"

POSITIVE_MOVIES_FILE = "my_pos_movies.json"
NEGATIVE_MOVIES_FILE = "my_neg_movies.json"
TASTE_PROFILE_FILE = "taste_profile.json"
FEEDBACK_FILE = "feedback.json"
TMDB_API_KEY_FILE = "tmdb_api_key.enc.json"

POSITIVE_ANCHOR_SCORE = 100
DEFAULT_NEGATIVE_ANCHOR_SCORE = 40
DEFAULT_POSITIVE_IMPORTANCE = 1.0
DEFAULT_NEGATIVE_IMPORTANCE = 1.0
TMDB_KEY_PASSWORD_ENV_NAMES = (
    "MOVIE_TMDB_KEY_PASSWORD",
    "TMDB_API_KEY_PASSWORD",
    "TMDB_KEY_PASSWORD",
)
TMDB_KEY_SESSION_FILE = ".tmdb_api_key_session.json"
TMDB_KEY_SESSION_DAYS = 3
# ===============================================

ROOT = Path(__file__).resolve().parent
TMDB_BASE_URL = "https://api.themoviedb.org/3"
EXIT_COMMANDS = {"q", "quit", "exit", "退出"}
TMDB_API_KEY = None

SCORE_LABELS = {
    "script": "剧本与人性深度",
    "style": "视听语言与导演风格",
    "taste": "口味契合度",
}

DEFAULT_TASTE_PROFILE = {
    "version": 1,
    "description": "个人电影口味配置。正向片单统一视为 100 分锚点，反向片单表示 50 分以下、有明确拒绝点的锚点。",
    "anchor_scores": {
        "positive": 100,
        "negative_default": 40,
        "negative_max": 49,
    },
    "sample_importance": {
        "positive": 1.0,
        "negative": 1.0,
        "feedback": 2.0,
    },
    "ollama_options": {
        "temperature": 0.1,
    },
    "learned_core_features": {
        "positive": [],
        "negative": [],
    },
    "score_calibration": {
        "anchor_blend": 0.35,
        "minimum_anchor_relevance": 0.15,
        "movies_details_positive_floor": 82,
        "movies_details_negative_ceiling": 60,
    },
    "selection": {
        "positive_limit": 8,
        "negative_limit": 8,
        "feedback_limit": 6,
    },
    "dimension_weights": {
        "剧本与人性深度": 2.0,
        "视听语言与导演风格": 1.0,
        "口味契合度": 2.0,
    },
    "taste_dimensions": [
        {
            "name": "剧本复杂度",
            "weight": 1.3,
            "high_score_signal": "人物动机复杂，冲突有递进，结局不是简单爽感收束。",
            "low_score_signal": "剧情依靠套路推进，人物只是功能性工具。",
        },
        {
            "name": "人性灰度",
            "weight": 1.4,
            "high_score_signal": "人物有道德矛盾、阶层压力或命运困境。",
            "low_score_signal": "善恶二分明显，人物缺少复杂性。",
        },
        {
            "name": "时代和社会底色",
            "weight": 1.2,
            "high_score_signal": "个人命运能映射时代、政治、历史或社会结构。",
            "low_score_signal": "故事只停留在表层事件，没有时代厚度。",
        },
        {
            "name": "视听克制与留白",
            "weight": 1.0,
            "high_score_signal": "镜头、节奏、声音和沉默能表达人物内心。",
            "low_score_signal": "依赖解释性台词、配乐煽情或过度剪辑。",
        },
        {
            "name": "商业套路风险",
            "weight": 1.4,
            "high_score_signal": "类型元素服务主题，而不是替代主题。",
            "low_score_signal": "爆米花奇观、强行反转、公式化成长或廉价燃点过多。",
        },
        {
            "name": "情绪真诚度",
            "weight": 1.1,
            "high_score_signal": "情绪来自人物处境和长期铺垫。",
            "low_score_signal": "靠台词喊口号、音乐推泪点或强行煽情。",
        },
        {
            "name": "爽感奇观题材加分",
            "weight": 1.0,
            "high_score_signal": "奇幻、大场面科幻、灾难、魔幻、大型动作片等题材，只要完成度不差，看起来很爽，本身就是天然加分项。",
            "low_score_signal": "同类题材如果只剩廉价特效、空洞打斗或无意义爆炸，则不能因为场面大而加分。",
        },
        {
            "name": "真实改编和历史纪实加分",
            "weight": 1.1,
            "high_score_signal": "真实故事改编、人物传记、历史纪实改编、重大事件还原等题材天然加分，尤其是能把真实人物处境拍出力量时。",
            "low_score_signal": "如果真实题材只是流水账、伟光正宣传或把复杂历史简单化，则降低加分。",
        },
        {
            "name": "坚韧勇敢和情感关系深剖加分",
            "weight": 1.3,
            "high_score_signal": "刻画人的坚韧、勇敢、自由意志，或极度深刻剖析亲密关系、家庭关系、情感创伤时，天然加分。",
            "low_score_signal": "如果坚韧勇敢只是口号，情感关系只是狗血、误会或廉价催泪，则不加分。",
        },
        {
            "name": "易踩雷题材减分",
            "weight": 1.2,
            "high_score_signal": "恐怖片、纯商业片、悬疑烧脑、战争片、抽象艺术电影如果有极强人性厚度、历史质感或情感落点，可以抵消减分。",
            "low_score_signal": "恐怖片、大尺度惊吓、纯商业工业快餐、为了反转而反转的烧脑悬疑、战争奇观、过度抽象艺术电影，默认适当减分。",
        },
        {
            "name": "已喜欢导演加分",
            "weight": 0.8,
            "high_score_signal": "如果导演已经出现在正向片单或高分反馈电影中，说明该导演的表达方式可能符合你的口味，应适当加分。",
            "low_score_signal": "导演加分只能作为辅助信号；如果新片本身剧本薄、套路重或触发反向锚点，不能因为导演熟悉而给高分。",
        },
    ],
}


def json_path(file_name):
    return DATA_DIR / file_name


def write_json_file(file_name, data):
    write_json(json_path(file_name), data)


def read_json_file(file_name, default=None, create_if_missing=False):
    path = json_path(file_name)
    if not path.exists():
        if create_if_missing:
            write_json_file(file_name, default)
        return default

    try:
        return read_json(path, default)
    except json.JSONDecodeError as e:
        print(f"无法解析 {file_name}: {e}")
        return default


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


def parse_session_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


crypt32 = ctypes.WinDLL("crypt32.dll")
kernel32 = ctypes.WinDLL("kernel32.dll")


def _blob_from_bytes(data):
    if not data:
        return DATA_BLOB(0, None), None
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return DATA_BLOB(len(data), buffer), buffer


def dpapi_protect(text):
    data_blob, _ = _blob_from_bytes(text.encode("utf-8"))
    out_blob = DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(data_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise RuntimeError("CryptProtectData failed.")
    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return b64encode(protected).decode("ascii")
    finally:
        kernel32.LocalFree(out_blob.pbData)


def dpapi_unprotect(protected_text):
    encrypted = b64decode(protected_text)
    data_blob, _ = _blob_from_bytes(encrypted)
    out_blob = DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(data_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise RuntimeError("CryptUnprotectData failed.")
    try:
        plaintext = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return plaintext.decode("utf-8")
    finally:
        kernel32.LocalFree(out_blob.pbData)


def load_tmdb_key_session():
    session = read_json_file(TMDB_KEY_SESSION_FILE, None, create_if_missing=False)
    if not isinstance(session, dict):
        return None
    expires_at = parse_session_time(session.get("expires_at"))
    if not expires_at or utc_now() >= expires_at:
        return None
    try:
        key = dpapi_unprotect(session["key_dpapi"])
    except Exception:
        return None
    return key or None


def save_tmdb_key_session(key):
    expires_at = utc_now() + timedelta(days=TMDB_KEY_SESSION_DAYS)
    write_json_file(
        TMDB_KEY_SESSION_FILE,
        {
            "version": 1,
            "created_at": utc_now().isoformat(timespec="seconds") + "Z",
            "expires_at": expires_at.isoformat(timespec="seconds") + "Z",
            "protection": "Windows DPAPI current user",
            "key_dpapi": dpapi_protect(key),
        },
    )


def merge_dict(default, override):
    merged = dict(default)
    if not isinstance(override, dict):
        return merged

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_taste_profile():
    profile = read_json_file(
        TASTE_PROFILE_FILE,
        DEFAULT_TASTE_PROFILE,
        create_if_missing=True,
    )
    return merge_dict(DEFAULT_TASTE_PROFILE, profile)


def load_feedback():
    feedback = read_json_file(FEEDBACK_FILE, [], create_if_missing=True)
    if isinstance(feedback, list):
        return feedback
    print(f"{FEEDBACK_FILE} 应该是 JSON 数组，当前内容已被忽略。")
    return []


def save_feedback(feedback):
    write_json_file(FEEDBACK_FILE, feedback)


def alias_hit(title, aliases):
    if not aliases:
        return False
    return bool(title_aliases(str(title)) & set(aliases))


def load_anchor_movies(file_name, sentiment, default_target_score, excluded_aliases=None):
    movies = read_json_file(file_name, [], create_if_missing=False)
    if not isinstance(movies, list):
        print(f"{file_name} 应该是 JSON 数组，当前内容已被忽略。")
        return []

    anchors = []
    for item in movies:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        if alias_hit(title, excluded_aliases):
            continue
        target_score = item.get("target_score", default_target_score)
        if sentiment == "positive":
            target_score = POSITIVE_ANCHOR_SCORE
        else:
            target_score = max(0, min(49, int(float(target_score))))

        reason = str(item.get("core_reason") or item.get("reason", "")).strip()
        anchors.append(
            {
                "title": title,
                "sentiment": sentiment,
                "target_score": target_score,
                "reason": reason,
                "source": file_name,
            }
        )
    return anchors


def load_tmdb_api_key():
    session_key = load_tmdb_key_session()
    if session_key:
        print(f"TMDb API Key 已从 {TMDB_KEY_SESSION_DAYS} 天 session 加载。")
        return session_key

    payload = read_json_file(TMDB_API_KEY_FILE, None, create_if_missing=False)
    if not payload:
        print(f"缺少 {TMDB_API_KEY_FILE}，无法请求 TMDb。")
        return None

    for env_name in TMDB_KEY_PASSWORD_ENV_NAMES:
        passphrase = os.environ.get(env_name)
        if not passphrase:
            continue
        try:
            key = aes_gcm_decrypt(payload, passphrase)
        except Exception:
            print(f"环境变量 {env_name} 中的口令无法解密 TMDb API Key。")
            continue
        if key:
            save_tmdb_key_session(key)
            print(f"TMDb API Key 已通过环境变量 {env_name} 解密成功。")
            return key

    for attempt in range(3):
        passphrase = getpass("请输入 TMDb API Key 解密口令：")
        try:
            key = aes_gcm_decrypt(payload, passphrase)
        except Exception:
            print("解密失败，请确认口令。")
            continue
        if key:
            save_tmdb_key_session(key)
            print("TMDb API Key 解密成功。")
            return key

    print("连续解密失败，程序退出。")
    return None


def get_movie_from_tmdb(title):
    """从 TMDb 抓取电影数据。"""
    if not TMDB_API_KEY:
        print("TMDb API Key 尚未解密。")
        return None

    search_url = f"{TMDB_BASE_URL}/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": title, "language": "zh-CN"}

    try:
        response = requests.get(search_url, params=params, timeout=15).json()
        if not response.get("results"):
            return None

        movie_data = response["results"][0]
        movie_id = movie_data["id"]

        detail_url = f"{TMDB_BASE_URL}/movie/{movie_id}"
        detail_params = {
            "api_key": TMDB_API_KEY,
            "language": "zh-CN",
            "append_to_response": "credits",
        }
        detail = requests.get(detail_url, params=detail_params, timeout=15).json()

        genres = [g["name"] for g in detail.get("genres", [])]
        directors = [
            c["name"]
            for c in detail.get("credits", {}).get("crew", [])
            if c.get("job") == "Director"
        ]

        return {
            "tmdb_id": detail.get("id"),
            "title": detail.get("title") or movie_data.get("title") or title,
            "original_title": detail.get("original_title"),
            "release_date": detail.get("release_date"),
            "overview": detail.get("overview"),
            "genres": genres,
            "directors": directors,
            "tmdb_rating": detail.get("vote_average"),
        }
    except Exception as e:
        print(f"TMDb 数据抓取失败，请检查网络环境或 API Key。错误: {e}")
        return None


def text_for_movie(movie_info):
    fields = [
        movie_info.get("title"),
        movie_info.get("original_title"),
        movie_info.get("overview"),
        " ".join(movie_info.get("genres") or []),
        " ".join(movie_info.get("directors") or []),
    ]
    return " ".join(str(field) for field in fields if field)


def text_for_anchor(anchor):
    return " ".join(
        str(anchor.get(key, ""))
        for key in ("title", "reason", "error_note", "overview")
        if anchor.get(key)
    )


def tokenize(text):
    text = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9'-]{1,}", text))

    for chunk in re.findall(r"[\u3400-\u9fff]+", text):
        if len(chunk) <= 2:
            tokens.add(chunk)
            continue
        for size in (2, 3, 4):
            if len(chunk) >= size:
                for i in range(len(chunk) - size + 1):
                    tokens.add(chunk[i : i + size])
    return tokens


def relevance_score(movie_info, anchor):
    target_text = text_for_movie(movie_info)
    anchor_text = text_for_anchor(anchor)
    target_tokens = tokenize(target_text)
    anchor_tokens = tokenize(anchor_text)
    if not target_tokens or not anchor_tokens:
        return 0.0

    overlap = target_tokens & anchor_tokens
    score = len(overlap) / math.sqrt(len(anchor_tokens))

    target_title = str(movie_info.get("title") or "").lower()
    anchor_title = str(anchor.get("title") or "").lower()
    if target_title and anchor_title:
        if target_title in anchor_title or anchor_title in target_title:
            score += 8.0

    for genre in movie_info.get("genres") or []:
        if genre and genre in anchor_text:
            score += 1.5

    for director in movie_info.get("directors") or []:
        if director and director in anchor_text:
            score += 2.0

    return round(score, 4)


def select_relevant_anchors(movie_info, anchors, limit):
    ranked = []
    for anchor in anchors:
        score = relevance_score(movie_info, anchor)
        ranked.append((score, anchor))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[:limit]


def find_known_label(movie_name):
    aliases = title_aliases(movie_name)

    feedback_matches = []
    for item in load_feedback():
        if not isinstance(item, dict) or item.get("actual_score") is None:
            continue
        title = str(item.get("title") or item.get("query") or "").strip()
        if title and alias_hit(title, aliases):
            feedback_matches.append(item)

    if feedback_matches:
        latest = feedback_matches[-1]
        score = max(0.0, min(100.0, float(latest["actual_score"])))
        return {
            "source": FEEDBACK_FILE,
            "sentiment": "feedback",
            "title": latest.get("title") or movie_name,
            "target_score": score,
            "reason": latest.get("error_note", ""),
            "movie_info": latest.get("movie_info") if isinstance(latest.get("movie_info"), dict) else None,
        }

    for item in read_json_file(POSITIVE_MOVIES_FILE, [], create_if_missing=False):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title and alias_hit(title, aliases):
            return {
                "source": POSITIVE_MOVIES_FILE,
                "sentiment": "positive",
                "title": title,
                "target_score": float(POSITIVE_ANCHOR_SCORE),
                "reason": item.get("core_reason") or item.get("reason", ""),
                "movie_info": None,
            }

    for item in read_json_file(NEGATIVE_MOVIES_FILE, [], create_if_missing=False):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title and alias_hit(title, aliases):
            target_score = item.get("target_score", DEFAULT_NEGATIVE_ANCHOR_SCORE)
            return {
                "source": NEGATIVE_MOVIES_FILE,
                "sentiment": "negative",
                "title": title,
                "target_score": float(max(0, min(49, int(float(target_score))))),
                "reason": item.get("core_reason") or item.get("reason", ""),
                "movie_info": None,
            }

    return None


def find_movies_details_label(movie_name):
    aliases = title_aliases(movie_name)
    for movie in iter_movies_details():
        title = movie.get("title", "")
        if title and alias_hit(title, aliases):
            return {
                "source": "movies_details",
                "source_file": movie.get("source_file"),
                "sentiment": movie.get("sentiment"),
                "title": title,
            }
    return None


def known_label_evaluation(movie_name, label):
    score = round(float(label["target_score"]), 1)
    movie_info = label.get("movie_info") or {
        "tmdb_id": None,
        "title": label.get("title") or movie_name,
        "original_title": None,
        "release_date": None,
        "overview": None,
        "genres": [],
        "directors": [],
        "tmdb_rating": None,
    }
    reason = label.get("reason") or "已存在于你的人工标注数据中。"
    return {
        "query": movie_name,
        "movie_info": movie_info,
        "model_output": f"已命中人工标注：{label['source']}。{reason}",
        "dimension_scores": {
            SCORE_LABELS["script"]: score,
            SCORE_LABELS["style"]: score,
            SCORE_LABELS["taste"]: score,
        },
        "predicted_score": score,
        "raw_model_score": score,
        "calibration": {
            "mode": "known_label",
            "source": label["source"],
            "sentiment": label["sentiment"],
            "target_score": score,
        },
        "positive_importance": None,
        "negative_importance": None,
        "selected_anchors": {
            "positive": [],
            "negative": [],
            "feedback": [],
        },
    }


def anchor_weighted_score(ranked_anchors, importance, minimum_relevance):
    total = 0.0
    weight_total = 0.0
    for relevance, anchor in ranked_anchors:
        if relevance < minimum_relevance:
            continue
        weight = max(0.0, float(importance)) * max(0.0, float(relevance))
        if weight <= 0:
            continue
        total += float(anchor["target_score"]) * weight
        weight_total += weight
    if not weight_total:
        return None
    return round(total / weight_total, 1)


def calibrated_score(
    raw_score,
    profile,
    selected_positive,
    selected_negative,
    selected_feedback,
    positive_importance,
    negative_importance,
):
    if raw_score is None:
        return None, {"mode": "unparsed_model_score"}

    calibration = profile.get("score_calibration", {})
    blend = max(0.0, min(1.0, float(calibration.get("anchor_blend", 0.35))))
    minimum_relevance = max(
        0.0,
        float(calibration.get("minimum_anchor_relevance", 0.15)),
    )
    feedback_importance = float(profile.get("sample_importance", {}).get("feedback", 2.0))

    anchor_scores = []
    for name, score in (
        ("positive", anchor_weighted_score(selected_positive, positive_importance, minimum_relevance)),
        ("negative", anchor_weighted_score(selected_negative, negative_importance, minimum_relevance)),
        ("feedback", anchor_weighted_score(selected_feedback, feedback_importance, minimum_relevance)),
    ):
        if score is not None:
            anchor_scores.append((name, score))

    if not anchor_scores or blend <= 0:
        return raw_score, {
            "mode": "model_only",
            "raw_score": raw_score,
            "anchor_scores": dict(anchor_scores),
        }

    anchor_average = sum(score for _, score in anchor_scores) / len(anchor_scores)
    final = round((raw_score * (1.0 - blend)) + (anchor_average * blend), 1)
    return final, {
        "mode": "model_anchor_blend",
        "raw_score": raw_score,
        "anchor_average": round(anchor_average, 1),
        "anchor_blend": blend,
        "minimum_anchor_relevance": minimum_relevance,
        "anchor_scores": dict(anchor_scores),
    }


def apply_movies_details_calibration(score, profile, movies_details_label):
    if score is None or not movies_details_label:
        return score, None

    calibration = profile.get("score_calibration", {})
    sentiment = movies_details_label.get("sentiment")
    if sentiment == "positive":
        floor = float(calibration.get("movies_details_positive_floor", 82))
        if score < floor:
            return floor, {
                "mode": "movies_details_positive_floor",
                "before": score,
                "after": floor,
                "source_file": movies_details_label.get("source_file"),
            }
    elif sentiment == "negative":
        ceiling = float(calibration.get("movies_details_negative_ceiling", 60))
        if score > ceiling:
            return ceiling, {
                "mode": "movies_details_negative_ceiling",
                "before": score,
                "after": ceiling,
                "source_file": movies_details_label.get("source_file"),
            }
    return score, None


def feedback_to_anchors(feedback, excluded_aliases=None):
    anchors = []
    for item in feedback:
        if not isinstance(item, dict):
            continue
        actual_score = item.get("actual_score")
        title = item.get("title")
        if actual_score is None or not title:
            continue
        if alias_hit(title, excluded_aliases):
            continue
        movie_info = item.get("movie_info") if isinstance(item.get("movie_info"), dict) else {}
        anchors.append(
            {
                "title": title,
                "sentiment": "feedback",
                "target_score": actual_score,
                "reason": item.get("error_note", ""),
                "overview": movie_info.get("overview", ""),
                "source": FEEDBACK_FILE,
                "predicted_score": item.get("predicted_score"),
            }
        )
    return anchors


def format_anchor_list(title, ranked_anchors):
    if not ranked_anchors:
        return f"{title}\n- 暂无可用锚点。"

    lines = [title]
    for relevance, anchor in ranked_anchors:
        sentiment = anchor.get("sentiment")
        if sentiment == "positive":
            label = "正向 100 分锚点"
        elif sentiment == "negative":
            label = "反向 50 分以下锚点"
        else:
            label = "历史反馈锚点"

        reason = anchor.get("reason") or "未提供原因"
        predicted = anchor.get("predicted_score")
        predicted_text = f"；上次模型预测 {predicted}/100" if predicted is not None else ""
        lines.append(
            f"- 《{anchor['title']}》 [{label}] 标定分 {anchor['target_score']}/100"
            f"{predicted_text}；相关度 {relevance:.2f}\n  依据: {reason}"
        )
    return "\n".join(lines)


def format_taste_dimensions(profile):
    lines = []
    for item in profile.get("taste_dimensions", []):
        lines.append(
            f"- {item.get('name')}，权重 {item.get('weight')}: "
            f"高分信号：{item.get('high_score_signal')}；"
            f"低分信号：{item.get('low_score_signal')}"
        )
    return "\n".join(lines)


def format_learned_core_features(profile):
    features = profile.get("learned_core_features", {})
    positive = features.get("positive", []) if isinstance(features, dict) else []
    negative = features.get("negative", []) if isinstance(features, dict) else []
    lines = []

    if positive:
        lines.append("高分核心特征：")
        for item in positive:
            if isinstance(item, dict):
                lines.append(f"- {item.get('name')}: {item.get('signal')}")
            else:
                lines.append(f"- {item}")

    if negative:
        lines.append("低分/踩雷核心特征：")
        for item in negative:
            if isinstance(item, dict):
                lines.append(f"- {item.get('name')}: {item.get('signal')}")
            else:
                lines.append(f"- {item}")

    return "\n".join(lines) if lines else "暂无额外提取特征。"


def build_system_prompt(
    profile,
    positive_anchors,
    negative_anchors,
    feedback_anchors,
    positive_importance,
    negative_importance,
):
    profile_importance = profile.get("sample_importance", {})
    feedback_importance = profile_importance.get("feedback", 2.0)

    return f"""
你是我的私人电影品味校准器，不是大众影评人。
你的任务不是给出客观均分，而是预测“我本人会不会喜欢这部电影”。

【评分锚点规则】
- 正向片单中的电影全部视为 100/100：不论从哪个角度，它们都是我值得看的电影。
- 反向片单中的电影不是 0 分片，而是 50 分以下的拒绝样本：它们一定有我接受不了的核心点。
- 反向锚点可以有 0-49 的 target_score；越低表示越不能接受。
- 历史反馈来自我看完后的真实纠偏，优先级最高。

【当前重要性】
- 正向样本重要性：{positive_importance:g}
- 反向样本重要性：{negative_importance:g}
- 历史反馈重要性：{feedback_importance:g}

【我的口味维度】
{format_taste_dimensions(profile)}

【从现有正负样本和反馈中提取出的核心特征】
{format_learned_core_features(profile)}

【题材倾向提醒】
- 奇幻、大场面科幻、灾难、魔幻、大型动作片：如果完成度不差，看起来很爽，天然加分。
- 真实故事改编、人物传记、历史纪实改编：天然加分。
- 刻画人的坚韧、勇敢、自由意志，或极度深刻剖析情感关系：天然加分。
- 恐怖片、纯商业片、悬疑烧脑、战争片、抽象艺术电影：默认适当减分；除非它们有足够强的人性厚度、历史质感或情感落点来抵消。
- 如果导演已经出现在我的正向片单或高分历史反馈中，说明我可能喜欢这个导演的表达方式，应适当加分；但这只是辅助信号，不能压过影片本身质量和反向风险。

【本次最相关的正向锚点】
{format_anchor_list("正向锚点", positive_anchors)}

【本次最相关的反向锚点】
{format_anchor_list("反向锚点", negative_anchors)}

【本次最相关的历史反馈】
{format_anchor_list("历史反馈", feedback_anchors)}

【打分要求】
1. “口味契合度”必须同时参考正向 100 分锚点、反向 50 分以下锚点、历史反馈三类证据。
2. 如果电影同时像正向和反向样本，请按重要性权重裁决，不要默认折中。
3. 如果信息不足，评分要保守，不要因为大众高分、知名导演或大制作自动给高分。
4. 请点名说明最像哪几部正向锚点、最危险地接近哪几部反向锚点。

【请严格按照以下格式输出，用中文回答，评分均为整数】

── 三维度推荐评分（满分各 100 分）──
维度一·剧本与人性深度: [XX] 分
参考依据: [一句话说明该维度得分理由]

维度二·视听语言与导演风格: [XX] 分
参考依据: [一句话说明该维度得分理由]

维度三·口味契合度: [XX] 分
参考依据: [说明它更接近哪些正向锚点，以及是否触发哪些反向风险]

── 深度品鉴报告 ──
口味对齐阐述: [一句话说明它在我的审美里会比大众评分更高或更低]
- 击中我的地方: [2 点]
- 可能会让我感到平庸/踩雷的地方: [1-2 点]

老友沙发闲谈: [两三句自然的话]
"""


def parse_scores(output):
    patterns = {
        "script": r"维度一.*?[:：]\s*\[?(\d{1,3})\]?\s*分",
        "style": r"维度二.*?[:：]\s*\[?(\d{1,3})\]?\s*分",
        "taste": r"维度三.*?[:：]\s*\[?(\d{1,3})\]?\s*分",
    }
    scores = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, output, re.S)
        if match:
            scores[key] = max(0, min(100, int(match.group(1))))
    return scores


def weighted_score(scores, profile):
    if len(scores) != 3:
        return None

    weights_by_label = profile.get("dimension_weights", {})
    total = 0.0
    total_weight = 0.0
    for key, label in SCORE_LABELS.items():
        weight = float(weights_by_label.get(label, 1.0))
        total += scores[key] * weight
        total_weight += weight
    return round(total / total_weight, 1) if total_weight else None


def print_score_summary(scores, final_score, profile):
    print("\n" + "=" * 50)
    if len(scores) != 3 or final_score is None:
        print("未能从模型输出中解析出三个维度的评分，请检查输出格式。")
        print("=" * 50)
        return

    weights_by_label = profile.get("dimension_weights", {})
    print("三维度评分汇总：")
    for key, label in SCORE_LABELS.items():
        score = scores[key]
        weight = weights_by_label.get(label, 1.0)
        bar = "█" * (score // 5) + "░" * (20 - score // 5)
        print(f"  {label:<14} {bar} {score:>3}/100  权重×{weight:g}")
    print(f"\n加权综合推荐分数：{final_score} / 100")
    print("=" * 50)


def evaluate_movie(
    movie_name,
    positive_importance,
    negative_importance,
    excluded_aliases=None,
    respect_known_labels=True,
):
    if respect_known_labels:
        label = find_known_label(movie_name)
        if label:
            print(f"命中人工标注：《{label['title']}》 -> {label['target_score']}/100 ({label['source']})")
            return known_label_evaluation(movie_name, label)

    profile = load_taste_profile()
    movie_info = get_movie_from_tmdb(movie_name)
    if not movie_info:
        print(f"没能在数据库里找到电影《{movie_name}》。")
        return None

    positive_limit = int(profile.get("selection", {}).get("positive_limit", 8))
    negative_limit = int(profile.get("selection", {}).get("negative_limit", 8))
    feedback_limit = int(profile.get("selection", {}).get("feedback_limit", 6))

    positive_anchors = load_anchor_movies(
        POSITIVE_MOVIES_FILE,
        "positive",
        POSITIVE_ANCHOR_SCORE,
        excluded_aliases=excluded_aliases,
    )
    negative_anchors = load_anchor_movies(
        NEGATIVE_MOVIES_FILE,
        "negative",
        DEFAULT_NEGATIVE_ANCHOR_SCORE,
        excluded_aliases=excluded_aliases,
    )
    feedback_anchors = feedback_to_anchors(load_feedback(), excluded_aliases=excluded_aliases)

    selected_positive = select_relevant_anchors(movie_info, positive_anchors, positive_limit)
    selected_negative = select_relevant_anchors(movie_info, negative_anchors, negative_limit)
    selected_feedback = select_relevant_anchors(movie_info, feedback_anchors, feedback_limit)

    release_year = (movie_info.get("release_date") or "未知")[:4]
    print(f"\n成功找到电影：《{movie_info['title']}》 ({release_year})")
    print(f"导演: {', '.join(movie_info['directors']) or '未知'}")
    print(f"类型: {', '.join(movie_info['genres']) or '未知'}")
    print(f"TMDb 公开评分: {movie_info['tmdb_rating']}/10")
    print(f"口味权重: 正向×{positive_importance:g} / 反向×{negative_importance:g}")
    print(f"锚点筛选: 正向 {len(selected_positive)} / 反向 {len(selected_negative)} / 反馈 {len(selected_feedback)}")
    print("-" * 50)

    system_prompt = build_system_prompt(
        profile,
        selected_positive,
        selected_negative,
        selected_feedback,
        positive_importance,
        negative_importance,
    )
    user_content = f"请评估这部新电影：{json.dumps(movie_info, ensure_ascii=False)}"

    try:
        chat_kwargs = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        ollama_options = profile.get("ollama_options")
        if isinstance(ollama_options, dict) and ollama_options:
            chat_kwargs["options"] = ollama_options
        response = ollama.chat(**chat_kwargs)
    except Exception as e:
        print(f"本地模型调用失败，请确保 Ollama 正在后台运行。错误: {e}")
        return None

    output = response["message"]["content"]
    print(output)

    scores = parse_scores(output)
    raw_score = weighted_score(scores, profile)
    final_score, calibration = calibrated_score(
        raw_score,
        profile,
        selected_positive,
        selected_negative,
        selected_feedback,
        positive_importance,
        negative_importance,
    )
    movies_details_label = find_movies_details_label(movie_name)
    final_score, details_calibration = apply_movies_details_calibration(
        final_score,
        profile,
        movies_details_label,
    )
    if details_calibration:
        calibration = dict(calibration)
        calibration["movies_details_adjustment"] = details_calibration

    print_score_summary(scores, final_score, profile)
    if calibration.get("mode") == "model_anchor_blend":
        print(
            "锚点校准: "
            f"模型原始 {calibration['raw_score']} / "
            f"锚点均值 {calibration['anchor_average']} / "
            f"混合系数 {calibration['anchor_blend']}"
        )
    if details_calibration:
        print(
            "movies_details 校准: "
            f"{movies_details_label['sentiment']} / "
            f"{details_calibration['before']} -> {details_calibration['after']} "
            f"({details_calibration['source_file']})"
        )

    return {
        "query": movie_name,
        "movie_info": movie_info,
        "model_output": output,
        "dimension_scores": {
            SCORE_LABELS[key]: scores[key] for key in scores
        },
        "predicted_score": final_score,
        "raw_model_score": raw_score,
        "calibration": calibration,
        "movies_details_label": movies_details_label,
        "positive_importance": positive_importance,
        "negative_importance": negative_importance,
        "selected_anchors": {
            "positive": [anchor["title"] for _, anchor in selected_positive],
            "negative": [anchor["title"] for _, anchor in selected_negative],
            "feedback": [anchor["title"] for _, anchor in selected_feedback],
        },
    }


def ask_feedback(evaluation):
    if not evaluation:
        return

    score_text = input("\n你的真实评分 0-100（回车跳过反馈）：").strip()
    if not score_text:
        return

    try:
        actual_score = float(score_text)
    except ValueError:
        print("真实评分必须是数字，本次反馈已跳过。")
        return

    if actual_score < 0 or actual_score > 100:
        print("真实评分必须在 0-100 之间，本次反馈已跳过。")
        return

    error_note = input("哪里不准，或这部片真正击中/踩雷你的原因（可空）：").strip()
    feedback = load_feedback()
    movie_info = evaluation["movie_info"]
    feedback.append(
        {
            "title": movie_info.get("title"),
            "query": evaluation.get("query"),
            "tmdb_id": movie_info.get("tmdb_id"),
            "movie_info": movie_info,
            "predicted_score": evaluation.get("predicted_score"),
            "dimension_scores": evaluation.get("dimension_scores"),
            "actual_score": actual_score,
            "error_note": error_note,
            "positive_importance": evaluation.get("positive_importance"),
            "negative_importance": evaluation.get("negative_importance"),
            "selected_anchors": evaluation.get("selected_anchors"),
            "model_output": evaluation.get("model_output"),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    )
    save_feedback(feedback)
    print(f"已写入 {FEEDBACK_FILE}，当前累计反馈 {len(feedback)} 条。")


def parse_weight_command(command, positive_importance, negative_importance):
    parts = command.split()
    if len(parts) != 3:
        print("用法: :w 正向权重 反向权重，例如 :w 1.2 1.6")
        return positive_importance, negative_importance

    try:
        new_positive = float(parts[1])
        new_negative = float(parts[2])
    except ValueError:
        print("权重必须是数字，例如 :w 1.2 1.6")
        return positive_importance, negative_importance

    if new_positive < 0 or new_negative < 0:
        print("权重不能为负数。")
        return positive_importance, negative_importance

    print(f"已调整口味权重: 正向×{new_positive:g} / 反向×{new_negative:g}")
    return new_positive, new_negative


def print_profile_status():
    profile = load_taste_profile()
    feedback = load_feedback()
    selection = profile.get("selection", {})
    print(f"{TASTE_PROFILE_FILE}: 已加载 {len(profile.get('taste_dimensions', []))} 个口味维度。")
    print(f"{FEEDBACK_FILE}: 已累计 {len(feedback)} 条反馈。")
    print(
        "当前锚点数量: "
        f"正向 {selection.get('positive_limit')} / "
        f"反向 {selection.get('negative_limit')} / "
        f"反馈 {selection.get('feedback_limit')}"
    )


def sync_test_file_with_message():
    result = sync_missing_movies_test_file()
    print(
        f"已同步 missing_movies_for_test.txt: "
        f"{result['count']} 部待测试 "
        f"（正向 {result['positive']} / 反向 {result['negative']}）。"
    )


def run_console():
    global TMDB_API_KEY

    positive_importance = DEFAULT_POSITIVE_IMPORTANCE
    negative_importance = DEFAULT_NEGATIVE_IMPORTANCE

    load_taste_profile()
    load_feedback()
    sync_test_file_with_message()
    TMDB_API_KEY = load_tmdb_api_key()
    if not TMDB_API_KEY:
        return

    print("=" * 50)
    print("私人电影评估控制台（AES Key + JSON 配置 + JSON 反馈闭环）")
    print("=" * 50)
    print("输入电影名开始评估。")
    print("命令: :w 正向权重 反向权重 | :profile | :sync | q")

    while True:
        target_movie = input("\n请输入你想评估的电影名称：").strip()
        if not target_movie:
            continue

        if target_movie.lower() in EXIT_COMMANDS:
            print("已退出。")
            break

        if target_movie.startswith(":w"):
            positive_importance, negative_importance = parse_weight_command(
                target_movie,
                positive_importance,
                negative_importance,
            )
            continue

        if target_movie == ":profile":
            print_profile_status()
            continue

        if target_movie == ":sync":
            sync_test_file_with_message()
            continue

        evaluation = evaluate_movie(target_movie, positive_importance, negative_importance)
        ask_feedback(evaluation)


if __name__ == "__main__":
    run_console()
