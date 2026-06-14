from movie_library import (
    DATA_DIR,
    TEST_DIR,
    compact_title,
    iter_movies_details,
    read_json,
    title_aliases,
)

TEST_MOVIES_FILE = TEST_DIR / "missing_movies_for_test.txt"
IGNORED_JSON_FILES = {
    "taste_profile.json",
    "tmdb_api_key.enc.json",
}


def extract_titles(value):
    titles = []
    if isinstance(value, dict):
        title = value.get("title")
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
        for nested in value.values():
            titles.extend(extract_titles(nested))
    elif isinstance(value, list):
        for item in value:
            titles.extend(extract_titles(item))
    return titles


def existing_movie_aliases_with_sources():
    aliases = {}
    for path in sorted(DATA_DIR.glob("*.json")):
        if path.name in IGNORED_JSON_FILES:
            continue
        data = read_json(path, None)
        if data is None:
            continue
        for title in extract_titles(data):
            for alias in title_aliases(title):
                aliases.setdefault(alias, []).append(f"{path.name}: {title}")
    return aliases


def existing_movie_aliases():
    return set(existing_movie_aliases_with_sources())


def sync_missing_movies_test_file():
    known_aliases = existing_movie_aliases()
    seen_missing = set()
    rows = []

    for movie in iter_movies_details():
        aliases = title_aliases(movie["title"])
        if aliases & known_aliases:
            continue

        unique_key = compact_title(movie["title"])
        if not unique_key or unique_key in seen_missing:
            continue
        seen_missing.add(unique_key)

        rows.append(
            (
                movie["sentiment"],
                movie["source_file"],
                movie["title"],
            )
        )

    TEST_DIR.mkdir(parents=True, exist_ok=True)
    with open(TEST_MOVIES_FILE, "w", encoding="utf-8") as f:
        f.write("# Movies in movies_details that are not in any JSON movie data file\n")
        f.write("# Format: sentiment<TAB>source_file<TAB>movie_title\n\n")
        for sentiment, source_file, title in rows:
            f.write(f"{sentiment}\t{source_file}\t{title}\n")

    return {
        "path": str(TEST_MOVIES_FILE),
        "count": len(rows),
        "positive": sum(1 for row in rows if row[0] == "positive"),
        "negative": sum(1 for row in rows if row[0] == "negative"),
    }


def explain_title(title):
    known_aliases = existing_movie_aliases_with_sources()
    aliases = title_aliases(title)
    hits = {
        alias: known_aliases[alias]
        for alias in sorted(aliases)
        if alias in known_aliases
    }

    print(f"title: {title}")
    print(f"aliases: {', '.join(sorted(aliases)) or '(none)'}")
    if hits:
        print("status: will be removed from test file")
        for alias, sources in hits.items():
            print(f"hit alias: {alias}")
            for source in sources:
                print(f"  - {source}")
    else:
        print("status: will stay in test file")
