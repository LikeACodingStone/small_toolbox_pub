import argparse
import contextlib
import io
import json
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = ROOT / "code"
DATA_DIR = ROOT / "data"
TEST_DIR = ROOT / "test"
REPORT_DIR = TEST_DIR / "reports"
MISSING_FILE = TEST_DIR / "missing_movies_for_test.txt"
DEFAULT_JSON_REPORT = REPORT_DIR / "missing_movies_regression_tuning_report.json"
DEFAULT_MD_REPORT = REPORT_DIR / "missing_movies_regression_tuning_report.md"
TASTE_PROFILE_PATH = DATA_DIR / "taste_profile.json"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import evaluate
from movie_library import read_json, title_aliases, write_json
from sync_movies import sync_missing_movies_test_file


TUNED_PROFILE_SECTIONS = (
    "sample_importance",
    "selection",
    "dimension_weights",
    "score_calibration",
    "ollama_options",
)


def configure_utf8_output():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_utf8_output()


def now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clone_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def load_missing_movies(path):
    movies = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue

        parts = text.split("\t", 2)
        if len(parts) != 3:
            continue

        sentiment, source_file, title = parts
        if sentiment not in {"positive", "negative"}:
            continue

        movies.append(
            {
                "case_id": f"{sentiment}\t{source_file}\t{title}",
                "line_no": line_no,
                "sentiment": sentiment,
                "source_file": source_file,
                "title": title,
            }
        )
    return movies


def load_raw_profile():
    return read_json(TASTE_PROFILE_PATH, {})


def load_profile():
    return evaluate.merge_dict(evaluate.DEFAULT_TASTE_PROFILE, load_raw_profile())


def save_profile(profile):
    write_json(TASTE_PROFILE_PATH, profile)


def backup_profile():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = REPORT_DIR / f"taste_profile_before_missing_regression_{stamp}.json"
    if TASTE_PROFILE_PATH.exists():
        shutil.copy2(TASTE_PROFILE_PATH, backup_path)
    else:
        write_json(backup_path, {})
    return backup_path


def apply_candidate(profile, profile_patch):
    next_profile = clone_json(profile)
    for section, value in profile_patch.items():
        if isinstance(value, dict) and isinstance(next_profile.get(section), dict):
            next_profile.setdefault(section, {}).update(value)
        else:
            next_profile[section] = clone_json(value)
    return next_profile


def compact_profile(profile):
    return {
        section: clone_json(profile.get(section, {}))
        for section in TUNED_PROFILE_SECTIONS
        if section in profile
    }


def candidate_configs():
    return [
        {
            "name": "current_profile",
            "note": "当前 taste_profile 原样验证，作为基准。",
            "positive_importance": 1.0,
            "negative_importance": 1.0,
            "profile": {},
        },
        {
            "name": "label_guard_balanced",
            "note": "保留 movies_details 的正负向校准，并提高锚点参与度。",
            "positive_importance": 1.2,
            "negative_importance": 1.2,
            "profile": {
                "selection": {"positive_limit": 14, "negative_limit": 14, "feedback_limit": 12},
                "score_calibration": {
                    "anchor_blend": 0.45,
                    "minimum_anchor_relevance": 0.06,
                    "movies_details_positive_floor": 82,
                    "movies_details_negative_ceiling": 60,
                },
                "dimension_weights": {"剧本与人性深度": 2.0, "视听语言与导演风格": 0.7, "口味契合度": 3.6},
            },
        },
        {
            "name": "positive_90_negative_original",
            "note": "Current target: movies_details positive floor 90, negative keeps the original ceiling.",
            "positive_importance": 2.4,
            "negative_importance": 2.0,
            "profile": {
                "selection": {"positive_limit": 22, "negative_limit": 20, "feedback_limit": 22},
                "score_calibration": {
                    "anchor_blend": 0.65,
                    "minimum_anchor_relevance": 0.02,
                    "movies_details_positive_floor": 90,
                    "movies_details_negative_ceiling": 60,
                },
                "dimension_weights": {"å‰§æœ¬ä¸Žäººæ€§æ·±åº¦": 1.6, "è§†å¬è¯­è¨€ä¸Žå¯¼æ¼”é£Žæ ¼": 0.8, "å£å‘³å¥‘åˆåº¦": 5.0},
            },
        },
        {
            "name": "positive_floor_84",
            "note": "正向 missing 样本更强保护，防止喜欢的大场面/传记/坚韧题材被低估。",
            "positive_importance": 1.6,
            "negative_importance": 1.2,
            "profile": {
                "selection": {"positive_limit": 16, "negative_limit": 12, "feedback_limit": 12},
                "score_calibration": {
                    "anchor_blend": 0.45,
                    "minimum_anchor_relevance": 0.05,
                    "movies_details_positive_floor": 84,
                    "movies_details_negative_ceiling": 60,
                },
                "dimension_weights": {"剧本与人性深度": 1.8, "视听语言与导演风格": 0.9, "口味契合度": 4.0},
            },
        },
        {
            "name": "negative_ceiling_58",
            "note": "强化反向样本，避免恐怖、纯商业、抽象和踩雷题材被误推高。",
            "positive_importance": 1.2,
            "negative_importance": 1.8,
            "profile": {
                "selection": {"positive_limit": 12, "negative_limit": 18, "feedback_limit": 12},
                "score_calibration": {
                    "anchor_blend": 0.5,
                    "minimum_anchor_relevance": 0.05,
                    "movies_details_positive_floor": 82,
                    "movies_details_negative_ceiling": 58,
                },
                "dimension_weights": {"剧本与人性深度": 2.1, "视听语言与导演风格": 0.7, "口味契合度": 3.8},
            },
        },
        {
            "name": "taste_first_83_60",
            "note": "把口味契合度权重再拉高，正反向都按 90% 目标做稳。",
            "positive_importance": 1.6,
            "negative_importance": 1.6,
            "profile": {
                "selection": {"positive_limit": 16, "negative_limit": 16, "feedback_limit": 14},
                "score_calibration": {
                    "anchor_blend": 0.5,
                    "minimum_anchor_relevance": 0.04,
                    "movies_details_positive_floor": 83,
                    "movies_details_negative_ceiling": 60,
                },
                "dimension_weights": {"剧本与人性深度": 1.8, "视听语言与导演风格": 0.8, "口味契合度": 4.2},
            },
        },
        {
            "name": "strict_label_direction",
            "note": "强制正向更高、反向更低，适合作为 missing 标签回归的硬防线。",
            "positive_importance": 2.0,
            "negative_importance": 2.0,
            "profile": {
                "selection": {"positive_limit": 18, "negative_limit": 18, "feedback_limit": 14},
                "score_calibration": {
                    "anchor_blend": 0.55,
                    "minimum_anchor_relevance": 0.04,
                    "movies_details_positive_floor": 85,
                    "movies_details_negative_ceiling": 58,
                },
                "dimension_weights": {"剧本与人性深度": 1.7, "视听语言与导演风格": 0.8, "口味契合度": 4.6},
            },
        },
        {
            "name": "positive_anchor_heavy",
            "note": "扩大正向锚点召回，让已喜欢导演和正向类型更容易被识别。",
            "positive_importance": 2.4,
            "negative_importance": 1.5,
            "profile": {
                "selection": {"positive_limit": 20, "negative_limit": 14, "feedback_limit": 16},
                "score_calibration": {
                    "anchor_blend": 0.6,
                    "minimum_anchor_relevance": 0.03,
                    "movies_details_positive_floor": 86,
                    "movies_details_negative_ceiling": 62,
                },
                "dimension_weights": {"剧本与人性深度": 1.6, "视听语言与导演风格": 0.9, "口味契合度": 4.8},
            },
        },
        {
            "name": "negative_anchor_heavy",
            "note": "扩大反向锚点召回，优先压住明确拒绝点。",
            "positive_importance": 1.5,
            "negative_importance": 2.6,
            "profile": {
                "selection": {"positive_limit": 14, "negative_limit": 22, "feedback_limit": 16},
                "score_calibration": {
                    "anchor_blend": 0.6,
                    "minimum_anchor_relevance": 0.03,
                    "movies_details_positive_floor": 82,
                    "movies_details_negative_ceiling": 55,
                },
                "dimension_weights": {"剧本与人性深度": 2.2, "视听语言与导演风格": 0.6, "口味契合度": 4.2},
            },
        },
        {
            "name": "feedback_heavy",
            "note": "提高历史反馈权重，适合你继续手动反馈之后再跑。",
            "positive_importance": 1.7,
            "negative_importance": 2.0,
            "profile": {
                "sample_importance": {"feedback": 3.0},
                "selection": {"positive_limit": 16, "negative_limit": 18, "feedback_limit": 22},
                "score_calibration": {
                    "anchor_blend": 0.5,
                    "minimum_anchor_relevance": 0.04,
                    "movies_details_positive_floor": 84,
                    "movies_details_negative_ceiling": 58,
                },
                "dimension_weights": {"剧本与人性深度": 1.9, "视听语言与导演风格": 0.7, "口味契合度": 4.4},
            },
        },
        {
            "name": "broad_anchor_guard",
            "note": "尽量多看锚点，适合片名和题材信息比较分散的 missing 集合。",
            "positive_importance": 2.0,
            "negative_importance": 2.2,
            "profile": {
                "selection": {"positive_limit": 24, "negative_limit": 24, "feedback_limit": 24},
                "score_calibration": {
                    "anchor_blend": 0.65,
                    "minimum_anchor_relevance": 0.02,
                    "movies_details_positive_floor": 82,
                    "movies_details_negative_ceiling": 60,
                },
                "dimension_weights": {"剧本与人性深度": 1.8, "视听语言与导演风格": 0.7, "口味契合度": 4.8},
            },
        },
        {
            "name": "model_low_anchor_with_labels",
            "note": "降低锚点混合，检查模型本身评分加 movies_details 标签校准后的效果。",
            "positive_importance": 1.4,
            "negative_importance": 1.6,
            "profile": {
                "selection": {"positive_limit": 14, "negative_limit": 16, "feedback_limit": 12},
                "score_calibration": {
                    "anchor_blend": 0.25,
                    "minimum_anchor_relevance": 0.02,
                    "movies_details_positive_floor": 82,
                    "movies_details_negative_ceiling": 60,
                },
                "dimension_weights": {"剧本与人性深度": 2.0, "视听语言与导演风格": 0.7, "口味契合度": 3.4},
            },
        },
        {
            "name": "strict_best_effort",
            "note": "最后兜底：强正向地板和强反向上限，优先让标签回归达标。",
            "positive_importance": 3.0,
            "negative_importance": 3.0,
            "profile": {
                "sample_importance": {"feedback": 3.5},
                "selection": {"positive_limit": 26, "negative_limit": 26, "feedback_limit": 26},
                "score_calibration": {
                    "anchor_blend": 0.7,
                    "minimum_anchor_relevance": 0.01,
                    "movies_details_positive_floor": 88,
                    "movies_details_negative_ceiling": 55,
                },
                "dimension_weights": {"剧本与人性深度": 1.6, "视听语言与导演风格": 0.8, "口味契合度": 5.2},
            },
        },
    ]


def expand_candidates(rounds):
    candidates = candidate_configs()
    if rounds <= len(candidates):
        return candidates[:rounds]

    expanded = list(candidates)
    grid = [
        (1.4, 1.4, 0.35, 82, 60),
        (1.8, 2.4, 0.45, 84, 58),
        (2.4, 1.8, 0.55, 86, 60),
        (2.8, 2.8, 0.65, 88, 55),
    ]
    while len(expanded) < rounds:
        index = len(expanded) - len(candidates)
        pos_imp, neg_imp, blend, floor, ceiling = grid[index % len(grid)]
        expanded.append(
            {
                "name": f"auto_grid_{len(expanded) + 1:02d}",
                "note": "超过内置候选数量后的自动网格参数。",
                "positive_importance": pos_imp,
                "negative_importance": neg_imp,
                "profile": {
                    "selection": {
                        "positive_limit": 14 + (index % 4) * 4,
                        "negative_limit": 14 + ((index + 1) % 4) * 4,
                        "feedback_limit": 12 + (index % 4) * 4,
                    },
                    "score_calibration": {
                        "anchor_blend": blend,
                        "minimum_anchor_relevance": 0.02,
                        "movies_details_positive_floor": floor,
                        "movies_details_negative_ceiling": ceiling,
                    },
                    "dimension_weights": {
                        "剧本与人性深度": 1.6 + (index % 3) * 0.2,
                        "视听语言与导演风格": 0.7,
                        "口味契合度": 4.0 + (index % 4) * 0.4,
                    },
                },
            }
        )
    return expanded


def load_report(path):
    if not path.exists():
        return None
    return read_json(path, None)


def new_report(args, movies, backup_path, base_profile):
    return {
        "created_at": now_text(),
        "updated_at": None,
        "script": str(Path(__file__).resolve()),
        "missing_file": str(MISSING_FILE),
        "backup_profile_path": str(backup_path),
        "resume_supported": True,
        "save_policy": "Report is saved after every evaluated movie. Resume with --resume.",
        "base_profile": clone_json(base_profile),
        "thresholds": {
            "positive_minimum": args.positive_threshold,
            "negative_maximum": args.negative_threshold,
            "target_pass_rate": args.target_pass_rate,
            "ignore_data_failures": bool(getattr(args, "ignore_data_failures", False)),
        },
        "case_totals": {
            "total": len(movies),
            "positive": sum(1 for movie in movies if movie["sentiment"] == "positive"),
            "negative": sum(1 for movie in movies if movie["sentiment"] == "negative"),
        },
        "rounds": [],
        "best_round_id": None,
        "stop_reason": None,
        "applied_best": None,
    }


def save_report(path, report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report["updated_at"] = now_text()
    write_json(path, report)


def round_id_for(index, candidate):
    return f"round_{index:02d}_{candidate['name']}"


def get_or_create_round(report, round_id, candidate, effective_profile):
    for round_data in report.setdefault("rounds", []):
        if round_data.get("round_id") == round_id:
            return round_data

    round_data = {
        "round_id": round_id,
        "candidate_name": candidate["name"],
        "note": candidate.get("note"),
        "started_at": now_text(),
        "finished_at": None,
        "config": {
            "positive_importance": candidate["positive_importance"],
            "negative_importance": candidate["negative_importance"],
            "profile_patch": clone_json(candidate.get("profile", {})),
            "effective_profile": compact_profile(effective_profile),
        },
        "items": [],
        "metrics": {},
        "passed": False,
    }
    report["rounds"].append(round_data)
    return round_data


def append_or_replace_item(round_data, item):
    items = round_data.setdefault("items", [])
    for index, existing in enumerate(items):
        if existing.get("case_id") == item.get("case_id"):
            items[index] = item
            return
    items.append(item)


def completed_case_ids(round_data):
    return {
        item.get("case_id")
        for item in round_data.get("items", [])
        if item.get("status") == "ok"
    }


def score_passed(sentiment, score, positive_threshold, negative_threshold):
    if score is None:
        return False
    if sentiment == "positive":
        return score >= positive_threshold
    if sentiment == "negative":
        return score <= negative_threshold
    return False


def miss_severity(sentiment, score, positive_threshold, negative_threshold):
    if score is None:
        return 999.0
    if sentiment == "positive":
        return round(max(0.0, positive_threshold - float(score)), 1)
    if sentiment == "negative":
        return round(max(0.0, float(score) - negative_threshold), 1)
    return 999.0


def target_count(total, target_pass_rate):
    return int(math.ceil(total * target_pass_rate))


def rate(pass_count, total):
    return round(pass_count / total, 4) if total else None


def metrics_for_items(
    items,
    movies,
    positive_threshold,
    negative_threshold,
    target_pass_rate,
    ignore_data_failures=False,
):
    item_by_id = {item.get("case_id"): item for item in items}
    attempted = [item_by_id[movie["case_id"]] for movie in movies if movie["case_id"] in item_by_id]
    ok_items = [item for item in attempted if item.get("status") == "ok"]
    failed_items = [item for item in attempted if item.get("status") != "ok"]
    pending = len(movies) - len(attempted)
    ignored_failure_ids = {
        item.get("case_id")
        for item in failed_items
        if ignore_data_failures and item.get("case_id")
    }

    eligible_movies = [
        movie for movie in movies if movie["case_id"] not in ignored_failure_ids
    ]
    positive_movies = [movie for movie in eligible_movies if movie["sentiment"] == "positive"]
    negative_movies = [movie for movie in eligible_movies if movie["sentiment"] == "negative"]

    def pass_count_for(group):
        return sum(
            1
            for movie in group
            if (
                movie["case_id"] in item_by_id
                and item_by_id[movie["case_id"]].get("status") == "ok"
                and item_by_id[movie["case_id"]].get("passed")
            )
        )

    positive_pass = pass_count_for(positive_movies)
    negative_pass = pass_count_for(negative_movies)

    misses = []
    for movie in movies:
        item = item_by_id.get(movie["case_id"])
        if not item:
            continue
        if item.get("status") != "ok" or not item.get("passed"):
            misses.append(
                {
                    "title": movie["title"],
                    "sentiment": movie["sentiment"],
                    "source_file": movie["source_file"],
                    "predicted_score": item.get("predicted_score"),
                    "raw_model_score": item.get("raw_model_score"),
                    "status": item.get("status"),
                    "error": item.get("error"),
                    "severity": item.get("severity", 999.0),
                    "movies_details_adjusted": item.get("movies_details_adjusted", False),
                }
            )
    misses.sort(key=lambda item: float(item.get("severity") or 0), reverse=True)

    positive_total = len(positive_movies)
    negative_total = len(negative_movies)
    positive_rate = rate(positive_pass, positive_total)
    negative_rate = rate(negative_pass, negative_total)
    positive_required = target_count(positive_total, target_pass_rate)
    negative_required = target_count(negative_total, target_pass_rate)
    severity_sum = round(
        sum(float(item.get("severity") or 0) for item in misses) + pending * 999.0,
        1,
    )

    return {
        "total": len(movies),
        "attempted": len(attempted),
        "pending": pending,
        "ok": len(ok_items),
        "failed": len(failed_items),
        "ignored_failures": len(ignored_failure_ids),
        "positive_total": positive_total,
        "positive_required": positive_required,
        "positive_pass": positive_pass,
        "positive_pass_rate": positive_rate,
        "negative_total": negative_total,
        "negative_required": negative_required,
        "negative_pass": negative_pass,
        "negative_pass_rate": negative_rate,
        "misses": len(misses) + pending,
        "miss_severity_sum": severity_sum,
        "completed_round": pending == 0,
        "top_misses": misses[:20],
    }


def round_passed(metrics, target_pass_rate):
    return (
        metrics.get("completed_round", False)
        and metrics.get("positive_total", 0) > 0
        and metrics.get("negative_total", 0) > 0
        and (metrics.get("positive_pass_rate") or 0) >= target_pass_rate
        and (metrics.get("negative_pass_rate") or 0) >= target_pass_rate
    )


def round_rank(round_data):
    metrics = round_data.get("metrics") or {}
    pos_rate = metrics.get("positive_pass_rate") or 0
    neg_rate = metrics.get("negative_pass_rate") or 0
    avg_rate = (pos_rate + neg_rate) / 2
    min_rate = min(pos_rate, neg_rate)
    pos_shortfall = max(0, metrics.get("positive_required", 0) - metrics.get("positive_pass", 0))
    neg_shortfall = max(0, metrics.get("negative_required", 0) - metrics.get("negative_pass", 0))
    return (
        1 if round_data.get("passed") else 0,
        1 if metrics.get("completed_round") else 0,
        min_rate,
        avg_rate,
        -(pos_shortfall + neg_shortfall),
        -float(metrics.get("miss_severity_sum") or 0),
        -int(metrics.get("failed") or 0),
        int(metrics.get("attempted") or 0),
    )


def best_round(report):
    rounds = [round_data for round_data in report.get("rounds", []) if round_data.get("metrics")]
    if not rounds:
        return None
    return max(rounds, key=round_rank)


def candidate_by_round_id(candidates):
    return {
        round_id_for(index, candidate): candidate
        for index, candidate in enumerate(candidates, 1)
    }


def dry_run_score(movie, candidate):
    if movie["sentiment"] == "positive":
        return float(candidate.get("profile", {}).get("score_calibration", {}).get("movies_details_positive_floor", 85))
    return float(candidate.get("profile", {}).get("score_calibration", {}).get("movies_details_negative_ceiling", 55))


def evaluate_movie_case(movie, candidate, args, quiet):
    if args.dry_run:
        score = dry_run_score(movie, candidate)
        return {
            "case_id": movie["case_id"],
            "status": "ok",
            "sentiment": movie["sentiment"],
            "source_file": movie["source_file"],
            "title": movie["title"],
            "predicted_score": score,
            "raw_model_score": score,
            "passed": score_passed(
                movie["sentiment"],
                score,
                args.positive_threshold,
                args.negative_threshold,
            ),
            "severity": miss_severity(
                movie["sentiment"],
                score,
                args.positive_threshold,
                args.negative_threshold,
            ),
            "dry_run": True,
            "candidate_name": candidate["name"],
            "evaluated_at": now_text(),
        }

    console_output = None
    excluded_aliases = title_aliases(movie["title"])
    if quiet:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = evaluate.evaluate_movie(
                movie["title"],
                candidate["positive_importance"],
                candidate["negative_importance"],
                excluded_aliases=excluded_aliases,
                respect_known_labels=False,
            )
        console_output = buffer.getvalue()
    else:
        result = evaluate.evaluate_movie(
            movie["title"],
            candidate["positive_importance"],
            candidate["negative_importance"],
            excluded_aliases=excluded_aliases,
            respect_known_labels=False,
        )

    if not result:
        return {
            "case_id": movie["case_id"],
            "status": "failed",
            "sentiment": movie["sentiment"],
            "source_file": movie["source_file"],
            "title": movie["title"],
            "predicted_score": None,
            "raw_model_score": None,
            "passed": False,
            "severity": 999.0,
            "error": "No evaluation result. TMDb lookup, Ollama, or API request may have failed.",
            "console_output": console_output,
            "candidate_name": candidate["name"],
            "evaluated_at": now_text(),
        }

    score = result.get("predicted_score")
    calibration = result.get("calibration") or {}
    details_adjustment = calibration.get("movies_details_adjustment")
    return {
        "case_id": movie["case_id"],
        "status": "ok",
        "sentiment": movie["sentiment"],
        "source_file": movie["source_file"],
        "title": movie["title"],
        "tmdb_id": (result.get("movie_info") or {}).get("tmdb_id"),
        "movie_info": result.get("movie_info"),
        "predicted_score": score,
        "raw_model_score": result.get("raw_model_score"),
        "passed": score_passed(
            movie["sentiment"],
            score,
            args.positive_threshold,
            args.negative_threshold,
        ),
        "severity": miss_severity(
            movie["sentiment"],
            score,
            args.positive_threshold,
            args.negative_threshold,
        ),
        "dimension_scores": result.get("dimension_scores"),
        "selected_anchors": result.get("selected_anchors"),
        "calibration": calibration,
        "movies_details_label": result.get("movies_details_label"),
        "movies_details_adjusted": bool(details_adjustment),
        "movies_details_adjustment": details_adjustment,
        "model_output": result.get("model_output"),
        "console_output": console_output,
        "candidate_name": candidate["name"],
        "evaluated_at": now_text(),
    }


def md_escape(value):
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def fmt_rate(value):
    if value is None:
        return ""
    return f"{value * 100:.1f}%"


def write_markdown(path, report):
    thresholds = report.get("thresholds", {})
    best_id = report.get("best_round_id")
    lines = [
        "# Missing Movies Regression Tuning Report",
        "",
        f"- Updated at: {report.get('updated_at')}",
        f"- Missing file: `{report.get('missing_file')}`",
        f"- Best round: `{best_id or ''}`",
        f"- Stop reason: `{report.get('stop_reason') or ''}`",
        f"- Positive pass: score >= {thresholds.get('positive_minimum')}",
        f"- Negative pass: score <= {thresholds.get('negative_maximum')}",
        f"- Target pass rate: {fmt_rate(thresholds.get('target_pass_rate'))}",
        f"- Ignore data failures: {thresholds.get('ignore_data_failures', False)}",
        "",
        "## Round Summary",
        "",
        "| Round | Passed | Positive | Negative | Failed | Ignored | Misses | Severity |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for round_data in report.get("rounds", []):
        metrics = round_data.get("metrics", {})
        lines.append(
            f"| {md_escape(round_data.get('round_id'))} | "
            f"{'Y' if round_data.get('passed') else 'N'} | "
            f"{metrics.get('positive_pass', 0)}/{metrics.get('positive_total', 0)} ({fmt_rate(metrics.get('positive_pass_rate'))}) | "
            f"{metrics.get('negative_pass', 0)}/{metrics.get('negative_total', 0)} ({fmt_rate(metrics.get('negative_pass_rate'))}) | "
            f"{metrics.get('failed', 0)} | "
            f"{metrics.get('ignored_failures', 0)} | "
            f"{metrics.get('misses', 0)} | "
            f"{metrics.get('miss_severity_sum', '')} |"
        )

    for round_data in report.get("rounds", []):
        metrics = round_data.get("metrics", {})
        config = round_data.get("config", {})
        effective = config.get("effective_profile", {})
        lines.extend(
            [
                "",
                f"## {md_escape(round_data.get('round_id'))}",
                "",
                f"- Passed: {round_data.get('passed')}",
                f"- Note: {md_escape(round_data.get('note'))}",
                f"- Positive importance: {config.get('positive_importance')}",
                f"- Negative importance: {config.get('negative_importance')}",
                f"- Evaluated: {metrics.get('attempted')}/{metrics.get('total')}",
                f"- Ignored failures: {metrics.get('ignored_failures', 0)}",
                f"- Positive: {metrics.get('positive_pass')}/{metrics.get('positive_total')} ({fmt_rate(metrics.get('positive_pass_rate'))})",
                f"- Negative: {metrics.get('negative_pass')}/{metrics.get('negative_total')} ({fmt_rate(metrics.get('negative_pass_rate'))})",
                f"- Score calibration: `{json.dumps(effective.get('score_calibration', {}), ensure_ascii=False)}`",
                "",
                "### Top Misses",
                "",
                "| Sentiment | Score | Raw | Severity | Movie | Source | Adjusted |",
                "|---|---:|---:|---:|---|---|---|",
            ]
        )
        top_misses = metrics.get("top_misses") or []
        if top_misses:
            for item in top_misses:
                lines.append(
                    f"| {md_escape(item.get('sentiment'))} | "
                    f"{item.get('predicted_score', '')} | "
                    f"{item.get('raw_model_score', '')} | "
                    f"{item.get('severity', '')} | "
                    f"{md_escape(item.get('title'))} | "
                    f"{md_escape(item.get('source_file'))} | "
                    f"{'Y' if item.get('movies_details_adjusted') else ''} |"
                )
        else:
            lines.append("|  |  |  |  |  |  |  |")

        lines.extend(
            [
                "",
                "### All Items",
                "",
                "| Pass | Sentiment | Score | Raw | Movie | Source | Adjusted | Status |",
                "|---|---|---:|---:|---|---|---|---|",
            ]
        )
        items = sorted(
            round_data.get("items", []),
            key=lambda item: (
                item.get("passed", False),
                -float(item.get("severity") or 0),
                item.get("sentiment", ""),
                item.get("title", ""),
            ),
        )
        for item in items:
            lines.append(
                f"| {'Y' if item.get('passed') else 'N'} | "
                f"{md_escape(item.get('sentiment'))} | "
                f"{item.get('predicted_score', '')} | "
                f"{item.get('raw_model_score', '')} | "
                f"{md_escape(item.get('title'))} | "
                f"{md_escape(item.get('source_file'))} | "
                f"{'Y' if item.get('movies_details_adjusted') else ''} | "
                f"{md_escape(item.get('status'))} |"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_best_profile(report, candidates, base_profile, json_report_path, md_report_path, dry_run, no_apply_best):
    selected = best_round(report)
    if not selected:
        report["best_round_id"] = None
        return None

    report["best_round_id"] = selected["round_id"]
    candidates_by_round = candidate_by_round_id(candidates)
    candidate = candidates_by_round.get(selected["round_id"])
    if not candidate:
        report["applied_best"] = {
            "applied": False,
            "reason": "Best round candidate was not found in current candidate list.",
            "round_id": selected["round_id"],
            "updated_at": now_text(),
        }
        save_report(json_report_path, report)
        write_markdown(md_report_path, report)
        return selected

    if dry_run:
        report["applied_best"] = {
            "applied": False,
            "reason": "Dry run does not modify taste_profile.json.",
            "round_id": selected["round_id"],
            "updated_at": now_text(),
        }
    elif no_apply_best:
        report["applied_best"] = {
            "applied": False,
            "reason": "--no-apply-best was used.",
            "round_id": selected["round_id"],
            "updated_at": now_text(),
        }
    else:
        best_profile = apply_candidate(base_profile, candidate.get("profile", {}))
        save_profile(best_profile)
        report["applied_best"] = {
            "applied": True,
            "path": str(TASTE_PROFILE_PATH),
            "round_id": selected["round_id"],
            "candidate_name": candidate["name"],
            "updated_at": now_text(),
            "effective_profile": compact_profile(best_profile),
        }

    save_report(json_report_path, report)
    write_markdown(md_report_path, report)
    return selected


def main():
    parser = argparse.ArgumentParser(
        description="Run full missing_movies_for_test regression rounds and keep the best taste_profile parameters."
    )
    parser.add_argument("--rounds", "--max-rounds", dest="rounds", type=int, default=10)
    parser.add_argument("--positive-threshold", type=float, default=80.0)
    parser.add_argument("--negative-threshold", type=float, default=65.0)
    parser.add_argument("--target-pass-rate", type=float, default=0.9)
    parser.add_argument("--limit", type=int, help="Dev-only: only evaluate first N selected cases.")
    parser.add_argument("--offset", type=int, default=0, help="Dev-only: skip first N selected cases.")
    parser.add_argument("--sentiment", choices=["positive", "negative"], help="Dev-only: only test one group.")
    parser.add_argument("--restart", action="store_true", help="Start a fresh report. This is also the default.")
    parser.add_argument("--resume", action="store_true", help="Resume an existing report instead of starting fresh.")
    parser.add_argument("--dry-run", action="store_true", help="Exercise the full loop without TMDb/Ollama calls.")
    parser.add_argument("--no-sync", action="store_true", help="Do not refresh missing_movies_for_test.txt first.")
    parser.add_argument("--ignore-data-failures", action="store_true", help="Keep failed lookup/model cases in the report but exclude them from pass-rate denominators.")
    parser.add_argument("--no-apply-best", action="store_true", help="Do not write the best profile back at the end.")
    parser.add_argument("--continue-after-pass", action="store_true", help="Run all requested rounds even after one passes.")
    parser.add_argument("--verbose", action="store_true", help="Show full model output while running.")
    parser.add_argument("--quiet", action="store_true", help="Compatibility flag; quiet is the default.")
    parser.add_argument("--json-report", default=str(DEFAULT_JSON_REPORT))
    parser.add_argument("--md-report", default=str(DEFAULT_MD_REPORT))
    args = parser.parse_args()

    if args.rounds <= 0:
        raise SystemExit("--rounds must be greater than 0.")
    if not 0 < args.target_pass_rate <= 1:
        raise SystemExit("--target-pass-rate must be between 0 and 1.")

    if not args.no_sync:
        sync = sync_missing_movies_test_file()
        print(
            f"synced missing list: {sync['count']} "
            f"({sync['positive']} positive / {sync['negative']} negative)"
        )

    movies = load_missing_movies(MISSING_FILE)
    if args.sentiment:
        movies = [movie for movie in movies if movie["sentiment"] == args.sentiment]
    if args.offset:
        movies = movies[args.offset :]
    if args.limit is not None:
        movies = movies[: args.limit]

    if not movies:
        raise SystemExit("No validation cases found in missing_movies_for_test.txt.")

    print(
        "regression cases: "
        f"{len(movies)} total / "
        f"{sum(1 for movie in movies if movie['sentiment'] == 'positive')} positive / "
        f"{sum(1 for movie in movies if movie['sentiment'] == 'negative')} negative"
    )
    print(
        "pass criteria: "
        f"positive >= {args.positive_threshold:g}, "
        f"negative <= {args.negative_threshold:g}, "
        f"target {args.target_pass_rate * 100:.1f}% for each group"
    )

    raw_profile_before_run = load_raw_profile()
    current_profile = load_profile()
    backup_path = backup_profile()
    print(f"profile backup: {backup_path}")

    candidates = expand_candidates(args.rounds)
    if args.positive_threshold >= 90:
        candidates = sorted(
            candidates,
            key=lambda candidate: candidate.get("name") != "positive_90_negative_original",
        )
    json_report_path = Path(args.json_report)
    md_report_path = Path(args.md_report)

    if args.resume and not args.restart:
        report = load_report(json_report_path)
        if report and isinstance(report.get("base_profile"), dict):
            base_profile = evaluate.merge_dict(evaluate.DEFAULT_TASTE_PROFILE, report["base_profile"])
            print("resume mode: using base_profile saved in existing report")
        else:
            base_profile = current_profile
            report = new_report(args, movies, backup_path, base_profile)
    else:
        base_profile = current_profile
        report = new_report(args, movies, backup_path, base_profile)

    quiet = True if not args.verbose else False

    if not args.dry_run:
        evaluate.TMDB_API_KEY = evaluate.load_tmdb_api_key()
        if not evaluate.TMDB_API_KEY:
            save_profile(raw_profile_before_run)
            raise SystemExit("TMDb API key could not be loaded.")

    stop_requested = False
    interrupted = False

    try:
        for index, candidate in enumerate(candidates, 1):
            effective_profile = apply_candidate(base_profile, candidate.get("profile", {}))
            if not args.dry_run:
                save_profile(effective_profile)

            round_id = round_id_for(index, candidate)
            round_data = get_or_create_round(report, round_id, candidate, effective_profile)
            done = completed_case_ids(round_data) if args.resume and not args.restart else set()
            pending = [movie for movie in movies if movie["case_id"] not in done]

            print("=" * 70)
            print(f"{round_id}: full traversal {len(movies)} cases, pending {len(pending)}")

            for case_index, movie in enumerate(pending, 1):
                print(
                    f"[round {index}/{len(candidates)} | "
                    f"{case_index}/{len(pending)}] "
                    f"{movie['sentiment']} {movie['title']}"
                )
                try:
                    item = evaluate_movie_case(movie, candidate, args, quiet)
                except KeyboardInterrupt:
                    interrupted = True
                    print("interrupted, saving current report...")
                    raise
                except Exception as e:
                    item = {
                        "case_id": movie["case_id"],
                        "status": "failed",
                        "sentiment": movie["sentiment"],
                        "source_file": movie["source_file"],
                        "title": movie["title"],
                        "predicted_score": None,
                        "raw_model_score": None,
                        "passed": False,
                        "severity": 999.0,
                        "error": repr(e),
                        "candidate_name": candidate["name"],
                        "evaluated_at": now_text(),
                    }

                append_or_replace_item(round_data, item)
                round_data["metrics"] = metrics_for_items(
                    round_data["items"],
                    movies,
                    args.positive_threshold,
                    args.negative_threshold,
                    args.target_pass_rate,
                    args.ignore_data_failures,
                )
                round_data["passed"] = round_passed(round_data["metrics"], args.target_pass_rate)
                selected = best_round(report)
                report["best_round_id"] = selected["round_id"] if selected else None
                save_report(json_report_path, report)
                write_markdown(md_report_path, report)
                print(
                    f"score={item.get('predicted_score')} "
                    f"raw={item.get('raw_model_score')} "
                    f"pass={item.get('passed')} "
                    f"adjusted={'Y' if item.get('movies_details_adjusted') else 'N'}"
                )

            round_data["finished_at"] = now_text()
            round_data["metrics"] = metrics_for_items(
                round_data["items"],
                movies,
                args.positive_threshold,
                args.negative_threshold,
                args.target_pass_rate,
                args.ignore_data_failures,
            )
            round_data["passed"] = round_passed(round_data["metrics"], args.target_pass_rate)
            selected = best_round(report)
            report["best_round_id"] = selected["round_id"] if selected else None
            save_report(json_report_path, report)
            write_markdown(md_report_path, report)

            metrics = round_data["metrics"]
            print(
                f"{round_id} metrics: "
                f"positive {metrics['positive_pass']}/{metrics['positive_total']} "
                f"({fmt_rate(metrics['positive_pass_rate'])}), "
                f"negative {metrics['negative_pass']}/{metrics['negative_total']} "
                f"({fmt_rate(metrics['negative_pass_rate'])}), "
                f"failed {metrics['failed']}, misses {metrics['misses']}"
            )

            if round_data["passed"] and not args.continue_after_pass:
                report["stop_reason"] = "passed_target"
                stop_requested = True
                print(f"PASSED with {round_id}; stopping early and applying this profile.")
                break

        if not stop_requested and not interrupted:
            report["stop_reason"] = "max_rounds_exhausted"

    except KeyboardInterrupt:
        report["stop_reason"] = "interrupted"
    finally:
        if interrupted:
            selected = best_round(report)
            report["best_round_id"] = selected["round_id"] if selected else None
            report["applied_best"] = {
                "applied": False,
                "reason": "Interrupted before completion. Resume with --resume to continue from saved progress.",
                "updated_at": now_text(),
            }
            save_report(json_report_path, report)
            write_markdown(md_report_path, report)
            save_profile(raw_profile_before_run)
        else:
            selected = apply_best_profile(
                report,
                candidates,
                base_profile,
                json_report_path,
                md_report_path,
                args.dry_run,
                args.no_apply_best,
            )
            if args.dry_run or args.no_apply_best:
                save_profile(raw_profile_before_run)

        if selected:
            metrics = selected.get("metrics", {})
            print("=" * 70)
            print(f"best round: {selected.get('round_id')}")
            print(
                f"best metrics: positive {metrics.get('positive_pass')}/{metrics.get('positive_total')} "
                f"({fmt_rate(metrics.get('positive_pass_rate'))}), "
                f"negative {metrics.get('negative_pass')}/{metrics.get('negative_total')} "
                f"({fmt_rate(metrics.get('negative_pass_rate'))})"
            )
            print(f"json report: {json_report_path}")
            print(f"markdown report: {md_report_path}")


if __name__ == "__main__":
    main()
