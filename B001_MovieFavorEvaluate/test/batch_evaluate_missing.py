import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = ROOT / "code"
TEST_DIR = ROOT / "test"
REPORT_DIR = TEST_DIR / "reports"
MISSING_FILE = TEST_DIR / "missing_movies_for_test.txt"
DEFAULT_JSON_REPORT = REPORT_DIR / "missing_movies_batch_report.json"
DEFAULT_MD_REPORT = REPORT_DIR / "missing_movies_batch_report.md"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import evaluate
from sync_movies import sync_missing_movies_test_file


def load_missing_movies(path):
    movies = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue

        parts = text.split("\t", 2)
        if len(parts) != 3:
            movies.append(
                {
                    "line_no": line_no,
                    "sentiment": "unknown",
                    "source_file": "",
                    "title": text,
                }
            )
            continue

        sentiment, source_file, title = parts
        movies.append(
            {
                "line_no": line_no,
                "sentiment": sentiment,
                "source_file": source_file,
                "title": title,
            }
        )
    return movies


def load_existing_report(path):
    if not path.exists():
        return {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "updated_at": None,
            "items": [],
        }

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def movie_key(movie):
    return f"{movie['sentiment']}\t{movie['source_file']}\t{movie['title']}"


def completed_keys(report):
    keys = set()
    for item in report.get("items", []):
        if item.get("status") == "ok":
            keys.add(item.get("key"))
    return keys


def append_or_replace_item(report, item):
    items = report.setdefault("items", [])
    for index, existing in enumerate(items):
        if existing.get("key") == item.get("key"):
            items[index] = item
            return
    items.append(item)


def save_json_report(path, report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")


def score_value(item):
    score = item.get("predicted_score")
    return -1 if score is None else score


def write_markdown_report(path, report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ok_items = [item for item in report.get("items", []) if item.get("status") == "ok"]
    failed_items = [item for item in report.get("items", []) if item.get("status") != "ok"]
    ok_items.sort(key=score_value, reverse=True)

    lines = [
        "# Missing Movies Batch Report",
        "",
        f"- Updated at: {report.get('updated_at')}",
        f"- Success: {len(ok_items)}",
        f"- Failed: {len(failed_items)}",
        "",
        "## Scores",
        "",
        "| Score | Sentiment | Movie | Source | TMDb | Dimensions |",
        "|---:|---|---|---|---|---|",
    ]

    for item in ok_items:
        info = item.get("movie_info") or {}
        dimensions = item.get("dimension_scores") or {}
        dimension_text = "<br>".join(f"{k}: {v}" for k, v in dimensions.items())
        tmdb_text = f"{info.get('title', '')} ({(info.get('release_date') or '')[:4]})"
        lines.append(
            f"| {item.get('predicted_score', '')} | "
            f"{item.get('sentiment', '')} | "
            f"{item.get('title', '')} | "
            f"{item.get('source_file', '')} | "
            f"{tmdb_text} | "
            f"{dimension_text} |"
        )

    if failed_items:
        lines.extend(["", "## Failed", ""])
        for item in failed_items:
            lines.append(
                f"- {item.get('title')} ({item.get('source_file')}): {item.get('error')}"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate_one(movie, positive_importance, negative_importance):
    result = evaluate.evaluate_movie(
        movie["title"],
        positive_importance,
        negative_importance,
    )
    if not result:
        return {
            "key": movie_key(movie),
            "status": "failed",
            "sentiment": movie["sentiment"],
            "source_file": movie["source_file"],
            "title": movie["title"],
            "error": "No evaluation result. TMDb lookup, Ollama, or API request may have failed.",
            "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    return {
        "key": movie_key(movie),
        "status": "ok",
        "sentiment": movie["sentiment"],
        "source_file": movie["source_file"],
        "title": movie["title"],
        "tmdb_id": result.get("movie_info", {}).get("tmdb_id"),
        "movie_info": result.get("movie_info"),
        "predicted_score": result.get("predicted_score"),
        "dimension_scores": result.get("dimension_scores"),
        "selected_anchors": result.get("selected_anchors"),
        "model_output": result.get("model_output"),
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Only evaluate the first N pending movies.")
    parser.add_argument("--no-sync", action="store_true", help="Do not refresh missing_movies_for_test.txt first.")
    parser.add_argument("--restart", action="store_true", help="Ignore previous successful report entries.")
    parser.add_argument("--dry-run", action="store_true", help="Print the movie list without calling TMDb/Ollama.")
    parser.add_argument("--json-report", default=str(DEFAULT_JSON_REPORT))
    parser.add_argument("--md-report", default=str(DEFAULT_MD_REPORT))
    parser.add_argument("--positive-importance", type=float, default=evaluate.DEFAULT_POSITIVE_IMPORTANCE)
    parser.add_argument("--negative-importance", type=float, default=evaluate.DEFAULT_NEGATIVE_IMPORTANCE)
    args = parser.parse_args()

    if not args.no_sync:
        sync_result = sync_missing_movies_test_file()
        print(
            f"synced missing list: {sync_result['count']} movies "
            f"({sync_result['positive']} positive, {sync_result['negative']} negative)"
        )

    movies = load_missing_movies(MISSING_FILE)
    if args.limit is not None:
        movies = movies[: args.limit]

    if args.dry_run:
        for index, movie in enumerate(movies, 1):
            print(f"{index}. [{movie['sentiment']}] {movie['title']} ({movie['source_file']})")
        return

    evaluate.TMDB_API_KEY = evaluate.load_tmdb_api_key()
    if not evaluate.TMDB_API_KEY:
        return

    json_report_path = Path(args.json_report)
    md_report_path = Path(args.md_report)
    report = load_existing_report(json_report_path)
    done = set() if args.restart else completed_keys(report)

    pending = [movie for movie in movies if movie_key(movie) not in done]
    print(f"batch total: {len(movies)}, already done: {len(done)}, pending: {len(pending)}")

    for index, movie in enumerate(pending, 1):
        print("=" * 70)
        print(f"[{index}/{len(pending)}] {movie['title']} ({movie['sentiment']}, {movie['source_file']})")
        try:
            item = evaluate_one(
                movie,
                args.positive_importance,
                args.negative_importance,
            )
        except KeyboardInterrupt:
            print("interrupted, saving current report...")
            break
        except Exception as e:
            item = {
                "key": movie_key(movie),
                "status": "failed",
                "sentiment": movie["sentiment"],
                "source_file": movie["source_file"],
                "title": movie["title"],
                "error": repr(e),
                "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }

        append_or_replace_item(report, item)
        save_json_report(json_report_path, report)
        write_markdown_report(md_report_path, report)

        if item.get("status") == "ok":
            print(f"saved score: {item.get('predicted_score')} -> {json_report_path}")
        else:
            print(f"saved failure: {item.get('error')} -> {json_report_path}")

    save_json_report(json_report_path, report)
    write_markdown_report(md_report_path, report)
    print("=" * 70)
    print(f"JSON report: {json_report_path}")
    print(f"Markdown report: {md_report_path}")


if __name__ == "__main__":
    main()
