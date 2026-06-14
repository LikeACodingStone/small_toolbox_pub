import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = ROOT / "code"
DATA_DIR = ROOT / "data"
TEST_DIR = ROOT / "test"
REPORT_DIR = TEST_DIR / "reports"
DEFAULT_JSON_REPORT = REPORT_DIR / "auto_regression_report.json"
DEFAULT_MD_REPORT = REPORT_DIR / "auto_regression_report.md"
TASTE_PROFILE_PATH = DATA_DIR / "taste_profile.json"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import evaluate
from movie_library import read_json, title_aliases, write_json


def configure_utf8_output():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_utf8_output()


def now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_profile():
    return read_json(TASTE_PROFILE_PATH, evaluate.DEFAULT_TASTE_PROFILE)


def save_profile(profile):
    write_json(TASTE_PROFILE_PATH, profile)


def backup_profile():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = REPORT_DIR / f"taste_profile_before_auto_regression_{stamp}.json"
    shutil.copy2(TASTE_PROFILE_PATH, backup_path)
    return backup_path


def build_cases(include_feedback):
    cases = []
    seen = set()

    for item in evaluate.read_json_file(evaluate.POSITIVE_MOVIES_FILE, [], create_if_missing=False):
        if not isinstance(item, dict) or not item.get("title"):
            continue
        title = str(item["title"]).strip()
        aliases = title_aliases(title)
        key = next(iter(sorted(aliases)), title)
        if key in seen:
            continue
        seen.add(key)
        cases.append(
            {
                "id": f"positive::{title}",
                "group": "positive",
                "title": title,
                "target_score": 100.0,
                "pass_threshold": 80.0,
                "source": evaluate.POSITIVE_MOVIES_FILE,
            }
        )

    for item in evaluate.read_json_file(evaluate.NEGATIVE_MOVIES_FILE, [], create_if_missing=False):
        if not isinstance(item, dict) or not item.get("title"):
            continue
        title = str(item["title"]).strip()
        aliases = title_aliases(title)
        key = next(iter(sorted(aliases)), title)
        if key in seen:
            continue
        seen.add(key)
        target = item.get("target_score", evaluate.DEFAULT_NEGATIVE_ANCHOR_SCORE)
        cases.append(
            {
                "id": f"negative::{title}",
                "group": "negative",
                "title": title,
                "target_score": float(max(0, min(49, int(float(target))))),
                "pass_threshold": 65.0,
                "source": evaluate.NEGATIVE_MOVIES_FILE,
            }
        )

    if include_feedback:
        for index, item in enumerate(evaluate.load_feedback(), 1):
            if not isinstance(item, dict) or not item.get("title") or item.get("actual_score") is None:
                continue
            title = str(item["title"]).strip()
            score = float(item["actual_score"])
            group = "feedback_positive" if score >= 80 else "feedback_negative" if score <= 65 else "feedback_mid"
            cases.append(
                {
                    "id": f"feedback::{index}::{title}",
                    "group": group,
                    "title": title,
                    "target_score": score,
                    "pass_threshold": 80.0 if score >= 80 else 65.0 if score <= 65 else None,
                    "source": evaluate.FEEDBACK_FILE,
                }
            )

    return cases


def case_passed(case, predicted_score):
    if predicted_score is None:
        return False
    group = case["group"]
    if group in {"positive", "feedback_positive"}:
        return predicted_score >= 80
    if group in {"negative", "feedback_negative"}:
        return predicted_score <= 65
    return abs(predicted_score - case["target_score"]) <= 15


def metrics_for_items(items):
    evaluated = [item for item in items if item.get("status") == "ok"]
    failed = [item for item in items if item.get("status") != "ok"]
    positives = [item for item in evaluated if item["group"] == "positive"]
    negatives = [item for item in evaluated if item["group"] == "negative"]
    feedback = [item for item in evaluated if item["group"].startswith("feedback")]

    positive_pass = [item for item in positives if item["passed"]]
    negative_pass = [item for item in negatives if item["passed"]]
    feedback_pass = [item for item in feedback if item["passed"]]

    return {
        "evaluated": len(evaluated),
        "failed": len(failed),
        "positive_total": len(positives),
        "positive_pass": len(positive_pass),
        "positive_pass_rate": round(len(positive_pass) / len(positives), 4) if positives else None,
        "negative_total": len(negatives),
        "negative_pass": len(negative_pass),
        "negative_pass_rate": round(len(negative_pass) / len(negatives), 4) if negatives else None,
        "feedback_total": len(feedback),
        "feedback_pass": len(feedback_pass),
        "feedback_pass_rate": round(len(feedback_pass) / len(feedback), 4) if feedback else None,
    }


def overall_passed(metrics):
    positive_rate = metrics.get("positive_pass_rate")
    positive_total = metrics.get("positive_total", 0)
    negative_total = metrics.get("negative_total", 0)
    negative_pass = metrics.get("negative_pass", 0)
    return (
        positive_rate is not None
        and positive_total > 0
        and positive_rate >= 0.9
        and negative_total > 0
        and negative_total == negative_pass
        and metrics.get("failed", 0) == 0
    )


def load_report(path):
    if not path.exists():
        return {
            "created_at": now_text(),
            "updated_at": None,
            "rounds": [],
        }
    return read_json(path, {"created_at": now_text(), "rounds": []})


def save_report(path, report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report["updated_at"] = now_text()
    write_json(path, report)


def done_keys_for_round(report, round_id):
    for round_data in report.get("rounds", []):
        if round_data.get("round_id") == round_id:
            return {
                item.get("case_id")
                for item in round_data.get("items", [])
                if item.get("status") == "ok"
            }
    return set()


def get_or_create_round(report, round_id, config):
    for round_data in report.setdefault("rounds", []):
        if round_data.get("round_id") == round_id:
            return round_data
    round_data = {
        "round_id": round_id,
        "started_at": now_text(),
        "finished_at": None,
        "config": config,
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


def current_config(profile, positive_importance, negative_importance):
    return {
        "positive_importance": positive_importance,
        "negative_importance": negative_importance,
        "selection": profile.get("selection", {}),
        "dimension_weights": profile.get("dimension_weights", {}),
        "score_calibration": profile.get("score_calibration", {}),
    }


def apply_candidate(profile, candidate):
    profile = json.loads(json.dumps(profile, ensure_ascii=False))
    for section in ("selection", "dimension_weights", "score_calibration"):
        if section in candidate:
            profile.setdefault(section, {}).update(candidate[section])
    return profile


def candidate_configs():
    return [
        {
            "name": "baseline_known_labels",
            "positive_importance": 1.0,
            "negative_importance": 1.0,
            "respect_known_labels": True,
            "profile": {},
        },
        {
            "name": "stronger_negative_guard",
            "positive_importance": 1.1,
            "negative_importance": 1.8,
            "respect_known_labels": True,
            "profile": {
                "selection": {"positive_limit": 10, "negative_limit": 12, "feedback_limit": 8},
                "score_calibration": {"anchor_blend": 0.45, "minimum_anchor_relevance": 0.1},
                "dimension_weights": {"剧本与人性深度": 2.2, "视听语言与导演风格": 0.8, "口味契合度": 2.8},
            },
        },
        {
            "name": "taste_first",
            "positive_importance": 1.3,
            "negative_importance": 2.2,
            "respect_known_labels": True,
            "profile": {
                "selection": {"positive_limit": 12, "negative_limit": 14, "feedback_limit": 10},
                "score_calibration": {"anchor_blend": 0.55, "minimum_anchor_relevance": 0.08},
                "dimension_weights": {"剧本与人性深度": 2.0, "视听语言与导演风格": 0.7, "口味契合度": 3.4},
            },
        },
        {
            "name": "blind_generalization_check",
            "positive_importance": 1.3,
            "negative_importance": 2.2,
            "respect_known_labels": False,
            "profile": {
                "selection": {"positive_limit": 12, "negative_limit": 14, "feedback_limit": 10},
                "score_calibration": {"anchor_blend": 0.55, "minimum_anchor_relevance": 0.08},
                "dimension_weights": {"剧本与人性深度": 2.0, "视听语言与导演风格": 0.7, "口味契合度": 3.4},
            },
        },
    ]


def evaluate_case(case, candidate, dry_run):
    if dry_run:
        predicted = case["target_score"]
        return {
            "case_id": case["id"],
            "status": "ok",
            "group": case["group"],
            "title": case["title"],
            "target_score": case["target_score"],
            "predicted_score": predicted,
            "passed": case_passed(case, predicted),
            "dry_run": True,
            "evaluated_at": now_text(),
        }

    excluded_aliases = title_aliases(case["title"]) if not candidate["respect_known_labels"] else None
    result = evaluate.evaluate_movie(
        case["title"],
        candidate["positive_importance"],
        candidate["negative_importance"],
        excluded_aliases=excluded_aliases,
        respect_known_labels=candidate["respect_known_labels"],
    )
    if not result:
        return {
            "case_id": case["id"],
            "status": "failed",
            "group": case["group"],
            "title": case["title"],
            "target_score": case["target_score"],
            "predicted_score": None,
            "passed": False,
            "error": "No evaluation result.",
            "evaluated_at": now_text(),
        }

    predicted = result.get("predicted_score")
    return {
        "case_id": case["id"],
        "status": "ok",
        "group": case["group"],
        "title": case["title"],
        "target_score": case["target_score"],
        "predicted_score": predicted,
        "raw_model_score": result.get("raw_model_score"),
        "passed": case_passed(case, predicted),
        "movie_info": result.get("movie_info"),
        "dimension_scores": result.get("dimension_scores"),
        "selected_anchors": result.get("selected_anchors"),
        "calibration": result.get("calibration"),
        "model_output": result.get("model_output"),
        "evaluated_at": now_text(),
    }


def write_markdown(path, report):
    lines = [
        "# Auto Regression Report",
        "",
        f"- Updated at: {report.get('updated_at')}",
        "",
    ]
    for round_data in report.get("rounds", []):
        metrics = round_data.get("metrics", {})
        lines.extend(
            [
                f"## {round_data.get('round_id')}",
                "",
                f"- Passed: {round_data.get('passed')}",
                f"- Evaluated: {metrics.get('evaluated')} / Failed: {metrics.get('failed')}",
                f"- Positive: {metrics.get('positive_pass')}/{metrics.get('positive_total')} ({metrics.get('positive_pass_rate')})",
                f"- Negative: {metrics.get('negative_pass')}/{metrics.get('negative_total')} ({metrics.get('negative_pass_rate')})",
                "",
                "| Pass | Group | Movie | Target | Predicted | Calibration |",
                "|---|---|---|---:|---:|---|",
            ]
        )
        items = list(round_data.get("items", []))
        items.sort(key=lambda item: (item.get("passed", False), item.get("group", ""), item.get("title", "")))
        for item in items:
            cal = item.get("calibration") or {}
            lines.append(
                f"| {'Y' if item.get('passed') else 'N'} | "
                f"{item.get('group')} | {item.get('title')} | "
                f"{item.get('target_score')} | {item.get('predicted_score')} | "
                f"{cal.get('mode', '')} |"
            )
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Only test first N cases.")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-feedback", action="store_true")
    parser.add_argument("--blind", action="store_true", help="Only run the blind generalization candidate.")
    parser.add_argument("--json-report", default=str(DEFAULT_JSON_REPORT))
    parser.add_argument("--md-report", default=str(DEFAULT_MD_REPORT))
    args = parser.parse_args()

    base_profile = load_profile()
    backup_path = backup_profile()
    print(f"profile backup: {backup_path}")

    cases = build_cases(include_feedback=args.include_feedback)
    if args.limit is not None:
        cases = cases[: args.limit]
    print(f"test cases: {len(cases)}")

    candidates = candidate_configs()
    if args.blind:
        candidates = [item for item in candidates if item["name"] == "blind_generalization_check"]
    else:
        candidates = candidates[: args.max_rounds]

    json_report_path = Path(args.json_report)
    md_report_path = Path(args.md_report)
    report = {"created_at": now_text(), "updated_at": None, "rounds": []} if args.restart else load_report(json_report_path)

    if not args.dry_run and any(not c["respect_known_labels"] for c in candidates):
        evaluate.TMDB_API_KEY = evaluate.load_tmdb_api_key()
        if not evaluate.TMDB_API_KEY:
            save_profile(base_profile)
            return

    try:
        for index, candidate in enumerate(candidates, 1):
            profile = apply_candidate(base_profile, candidate["profile"])
            save_profile(profile)
            config = current_config(profile, candidate["positive_importance"], candidate["negative_importance"])
            config["respect_known_labels"] = candidate["respect_known_labels"]
            round_id = f"round_{index}_{candidate['name']}"
            round_data = get_or_create_round(report, round_id, config)
            done = set() if args.restart else done_keys_for_round(report, round_id)

            pending = [case for case in cases if case["id"] not in done]
            print("=" * 70)
            print(f"{round_id}: pending {len(pending)} / total {len(cases)}")
            for case_index, case in enumerate(pending, 1):
                print(f"[{case_index}/{len(pending)}] {case['group']} {case['title']}")
                try:
                    item = evaluate_case(case, candidate, args.dry_run)
                except KeyboardInterrupt:
                    print("interrupted, saving report...")
                    raise
                except Exception as e:
                    item = {
                        "case_id": case["id"],
                        "status": "failed",
                        "group": case["group"],
                        "title": case["title"],
                        "target_score": case["target_score"],
                        "predicted_score": None,
                        "passed": False,
                        "error": repr(e),
                        "evaluated_at": now_text(),
                    }

                append_or_replace_item(round_data, item)
                round_data["metrics"] = metrics_for_items(round_data["items"])
                round_data["passed"] = overall_passed(round_data["metrics"])
                save_report(json_report_path, report)
                write_markdown(md_report_path, report)
                print(
                    f"score={item.get('predicted_score')} target={item.get('target_score')} "
                    f"pass={item.get('passed')}"
                )

            round_data["finished_at"] = now_text()
            round_data["metrics"] = metrics_for_items(round_data["items"])
            round_data["passed"] = overall_passed(round_data["metrics"])
            save_report(json_report_path, report)
            write_markdown(md_report_path, report)

            print(f"metrics: {round_data['metrics']}")
            if round_data["passed"]:
                print(f"PASSED with {round_id}")
                return

        print("No candidate fully passed. Latest profile remains applied for inspection.")
    finally:
        if args.dry_run:
            save_profile(base_profile)


if __name__ == "__main__":
    main()
