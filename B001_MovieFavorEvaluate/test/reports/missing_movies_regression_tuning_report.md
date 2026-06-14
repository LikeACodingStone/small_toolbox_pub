# Missing Movies Regression Tuning Report

- Updated at: 2026-06-14T18:12:32+09:00
- Missing file: `D:\GithubFolder\small_toolbox_pub\B001_MovieFavorEvaluate\test\missing_movies_for_test.txt`
- Best round: `round_01_positive_90_negative_original`
- Stop reason: ``
- Positive pass: score >= 90.0
- Negative pass: score <= 65.0
- Target pass rate: 90.0%
- Ignore data failures: True

## Round Summary

| Round | Passed | Positive | Negative | Failed | Ignored | Misses | Severity |
|---|---|---:|---:|---:|---:|---:|---:|
| round_01_positive_90_negative_original | N | 0/52 (0.0%) | 14/18 (77.8%) | 2 | 2 | 58 | 57942.0 |

## round_01_positive_90_negative_original

- Passed: False
- Note: Current target: movies_details positive floor 90, negative keeps the original ceiling.
- Positive importance: 2.4
- Negative importance: 2.0
- Evaluated: 16/72
- Ignored failures: 2
- Positive: 0/52 (0.0%)
- Negative: 14/18 (77.8%)
- Score calibration: `{"anchor_blend": 0.65, "minimum_anchor_relevance": 0.02, "movies_details_positive_floor": 90, "movies_details_negative_ceiling": 60}`

### Top Misses

| Sentiment | Score | Raw | Severity | Movie | Source | Adjusted |
|---|---:|---:|---:|---|---|---|
| negative | None | None | 999.0 | 2001天空漫游 | 00 record.md |  |
| negative | None | None | 999.0 | 雷霆特工队 | 00 record.md |  |

### All Items

| Pass | Sentiment | Score | Raw | Movie | Source | Adjusted | Status |
|---|---|---:|---:|---|---|---|---|
| N | negative | None | None | 2001天空漫游 | 00 record.md |  | failed |
| N | negative | None | None | 雷霆特工队 | 00 record.md |  | failed |
| Y | negative | 60.0 | 70.6 | F1狂飙飞车 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 82.5 | 东京塔 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 83.0 | 了不起的盖茨比 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 50.6 | 咒怨 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 73.4 | 哪吒 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 71.2 | 壮志凌云：独行侠 | 00 record.md | Y | ok |
| Y | negative | 59.6 | 29.9 | 孤岛惊魂 | 00 record.md |  | ok |
| Y | negative | 60.0 | 72.3 | 巴比伦 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 83.0 | 戏台 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 48.4 | 死神来了 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 60.1 | 生化危机 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 75.6 | 祝你好运里奥·格兰德 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 63.7 | 鬼水怪谈 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 61.2 | 黑夜传说 | 00 record.md | Y | ok |
