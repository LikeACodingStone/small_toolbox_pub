# Initialization Template

`inition` is the template input area for a fresh personal movie preference project.

## Files

| File | Purpose |
|---|---|
| `positive.txt` | Plain text seed list for positive movies. One movie per line, preferably prefixed with `- `. |
| `negtive.txt` | Plain text seed list for negative movies. The filename intentionally follows the requested spelling. |
| `tmdb_key.txt` | Local setup file for the TMDb key and password. Keep real keys out of Git. |
| `rules.txt` | Preference rules used to initialize or refresh `data/taste_profile.json`. |
| `EnvSetup/envsetup.py` | Automation script that imports text seeds into JSON, encrypts the TMDb key, and syncs the encrypted SQLite database. |

## Run Setup

```powershell
python .\inition\EnvSetup\envsetup.py
```

The script will:

- Read `positive.txt` and `negtive.txt`.
- Use TMDb to resolve movie metadata.
- Append new movies to `data/my_pos_movies.json` and `data/my_neg_movies.json`.
- Remove processed lines from the text files.
- Store `rules.txt` into `data/taste_profile.json`.
- Create or reuse a three-day encrypted database session.
- Import plain JSON data into `data/movie_favor_secure.db`.

## Database Conversion

Import current plain JSON into encrypted SQLite:

```powershell
python .\code\secure_movie_db.py import-json
```

Export encrypted SQLite back to plain JSON:

```powershell
python .\code\secure_movie_db.py export-json --overwrite
```

Plain JSON remains the active format for the current evaluator. The encrypted database is an additional storage and migration layer.

