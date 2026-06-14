# Codex Prompt: First Automatic Regression Adjustment

Use this prompt with Codex when you want it to tune movie scoring parameters automatically.

## Regression Configuration

```yaml
rounds: 10
positive_pass_score: 80
negative_pass_score: 65
positive_target_pass_rate: 0.90
negative_target_pass_rate: 0.90
positive_test_file: test/positive_test.txt
negative_test_file: test/negitive_test.txt
profile_file: data/taste_profile.json
json_report: test/reports/first_auto_adjust_report.json
markdown_report: test/reports/first_auto_adjust_report.md
```

## Task Prompt

You are Codex working inside this movie preference evaluation project.

Run a real regression tuning workflow. A round means evaluating every movie in both `positive_test.txt` and `negitive_test.txt`, not a small sample.

Goal:

- At least 90% of positive test movies must score `>= 80`.
- At least 90% of negative test movies must score `<= 65`.
- If a round passes, stop early and keep that parameter set.
- If all 10 rounds fail, keep the best parameter set.

Process:

1. Read the current implementation and data format before editing.
2. Back up `data/taste_profile.json`.
3. Build candidate parameter sets by adjusting:
   - `sample_importance.positive`
   - `sample_importance.negative`
   - `sample_importance.feedback`
   - `selection.positive_limit`
   - `selection.negative_limit`
   - `selection.feedback_limit`
   - `dimension_weights`
   - `score_calibration.anchor_blend`
   - `score_calibration.minimum_anchor_relevance`
   - `score_calibration.movies_details_positive_floor`
   - `score_calibration.movies_details_negative_ceiling`
   - `ollama_options.temperature`
4. For each candidate, evaluate every positive and negative test movie.
5. Save progress after every movie so an interrupted run can resume.
6. Write JSON and Markdown reports with:
   - round config
   - every evaluated movie
   - raw model score
   - final predicted score
   - pass/fail result
   - calibration details
   - top misses
7. Apply the best parameter set to `data/taste_profile.json`.
8. If the run is interrupted, do not apply a partial best profile. Preserve the report so the next run can resume.

Important:

- Do not treat this Markdown file as executable code.
- Do not hard-code passwords or API keys.
- Use `MOVIE_TMDB_KEY_PASSWORD` or interactive password input for decrypting the TMDb key.
- Keep existing JSON files readable as plain JSON.
- Keep the encrypted SQLite database synchronized if the project has database conversion enabled.

