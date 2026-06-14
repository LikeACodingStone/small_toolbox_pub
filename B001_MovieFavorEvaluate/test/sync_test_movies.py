import argparse
import sys
from pathlib import Path


def configure_utf8_output():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


configure_utf8_output()

ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from sync_movies import explain_title, sync_missing_movies_test_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--explain", help="Explain whether a title is considered already covered.")
    args = parser.parse_args()

    if args.explain:
        explain_title(args.explain)
        return

    result = sync_missing_movies_test_file()
    print(
        f"synced {result['path']}: "
        f"{result['count']} movies "
        f"({result['positive']} positive, {result['negative']} negative)"
    )


if __name__ == "__main__":
    main()
