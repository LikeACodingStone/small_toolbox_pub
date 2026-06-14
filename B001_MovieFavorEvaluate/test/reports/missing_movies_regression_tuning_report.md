# Missing Movies Regression Tuning Report

- Updated at: 2026-06-14T11:23:03+09:00
- Missing file: `D:\GithubFolder\small_toolbox_pub\B001_MovieFavorEvaluate\test\missing_movies_for_test.txt`
- Best round: `round_01_current_profile`
- Stop reason: `passed_target`
- Positive pass: score >= 80.0
- Negative pass: score <= 65.0
- Target pass rate: 90.0%

## Round Summary

| Round | Passed | Positive | Negative | Failed | Misses | Severity |
|---|---|---:|---:|---:|---:|---:|
| round_01_current_profile | Y | 50/54 (92.6%) | 18/20 (90.0%) | 6 | 6 | 5994.0 |

## round_01_current_profile

- Passed: True
- Note: 当前 taste_profile 原样验证，作为基准。
- Positive importance: 1.0
- Negative importance: 1.0
- Evaluated: 74/74
- Positive: 50/54 (92.6%)
- Negative: 18/20 (90.0%)
- Score calibration: `{"anchor_blend": 0.55, "minimum_anchor_relevance": 0.08, "movies_details_positive_floor": 82, "movies_details_negative_ceiling": 60}`

### Top Misses

| Sentiment | Score | Raw | Severity | Movie | Source | Adjusted |
|---|---:|---:|---:|---|---|---|
| negative | None | None | 999.0 | 2001天空漫游 | 00 record.md |  |
| negative | None | None | 999.0 | 雷霆特工队 | 00 record.md |  |
| positive | None | None | 999.0 | 心灵点滴 (Soul?) | 06 治愈坚韧勇敢.md |  |
| positive | None | None | 999.0 | 总有一天 (Lang historie kort?) | 06 治愈坚韧勇敢.md |  |
| positive | None | None | 999.0 | The Hole 洞（1960 经典） | 08 经典高分.md |  |
| positive | None | None | 999.0 | 指环王三部曲 加长版 | 09 超长3小时起.md |  |

### All Items

| Pass | Sentiment | Score | Raw | Movie | Source | Adjusted | Status |
|---|---|---:|---:|---|---|---|---|
| N | negative | None | None | 2001天空漫游 | 00 record.md |  | failed |
| N | negative | None | None | 雷霆特工队 | 00 record.md |  | failed |
| N | positive | None | None | The Hole 洞（1960 经典） | 08 经典高分.md |  | failed |
| N | positive | None | None | 心灵点滴 (Soul?) | 06 治愈坚韧勇敢.md |  | failed |
| N | positive | None | None | 总有一天 (Lang historie kort?) | 06 治愈坚韧勇敢.md |  | failed |
| N | positive | None | None | 指环王三部曲 加长版 | 09 超长3小时起.md |  | failed |
| Y | negative | 60.0 | 72.3 | F1狂飙飞车 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 81.1 | 东京塔 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 83.9 | 了不起的盖茨比 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 52.3 | 危机13小时 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 81.1 | 后天 | 00 record.md | Y | ok |
| Y | negative | 50.1 | 27.8 | 咒怨 | 00 record.md |  | ok |
| Y | negative | 60.0 | 60.7 | 哪吒 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 73.4 | 壮志凌云：独行侠 | 00 record.md | Y | ok |
| Y | negative | 57.4 | 35.6 | 孤岛惊魂 | 00 record.md |  | ok |
| Y | negative | 60.0 | 70.6 | 巴比伦 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 81.1 | 戏台 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 48.4 | 死神来了 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 62.3 | 生化危机 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 60.1 | 真实谎言 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 75.6 | 祝你好运里奥·格兰德 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 75.6 | 金矿 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 69.4 | 鬼水怪谈 | 00 record.md | Y | ok |
| Y | negative | 60.0 | 71.7 | 黑夜传说 | 00 record.md | Y | ok |
| Y | positive | 82.0 | 81.1 | A Man Called Ove 一个叫欧维的男人决定去死 | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 83.0 | A Perfect World 完美的世界 | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 82.5 | Cinderella Man 铁拳男人 | 12 人物传记真实改编.md | Y | ok |
| Y | positive | 82.0 | 81.1 | Dear Comrades! 亲爱的同志 | 08 经典高分.md | Y | ok |
| Y | positive | 82.0 | 75.6 | Fly Away Home 伴你高飞 | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 82.5 | I Am Sam 我是山姆 | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 79.1 | Legends of the Fall 燃情岁月 | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 63.5 | Sin City 罪恶之城 | 04 文艺类.md | Y | ok |
| Y | positive | 82.0 | 63.9 | The Cure 鳄鱼波鞋走天涯 | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 65.6 | The Journey 旅途 | 04 文艺类.md | Y | ok |
| Y | positive | 82.0 | 81.1 | The King’s Speech 国王的演讲 | 12 人物传记真实改编.md | Y | ok |
| Y | positive | 82.0 | 73.4 | Togo 多哥 | 12 人物传记真实改编.md | Y | ok |
| Y | positive | 82.0 | 31.1 | Wall Street 华尔街 | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 71.1 | 不成问题的问题 | 02 华语.md | Y | ok |
| Y | positive | 82.0 | 70.1 | 加勒比海盗 Dead Man’s Chest | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 69.6 | 勇闯夺命岛 The Rock | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 54.0 | 卡萨布兰卡 Casablanca | 08 经典高分.md | Y | ok |
| Y | positive | 82.0 | 67.9 | 地心历险记 | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 65.6 | 城市英雄 (Falling Down?) | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 71.2 | 复仇者联盟 | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 90.4 | 天堂电影院 (Cinema Paradiso) | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 63.7 | 失控玩家 | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 71.2 | 头号玩家 | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 91.1 | 婚姻生活 | 09 超长3小时起.md |  | ok |
| Y | positive | 82.0 | 63.7 | 子弹横飞百老汇 Bullets Over Broadway | 03 帮派犯罪.md | Y | ok |
| Y | positive | 82.0 | 60.1 | 安娜 | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.1 | 92.5 | 心灵捕手 (Good Will Hunting) | 06 治愈坚韧勇敢.md |  | ok |
| Y | positive | 82.0 | 66.5 | 捕风追影 | 02 华语.md | Y | ok |
| Y | positive | 82.0 | 78.3 | 牯岭街少年杀人事件 | 09 超长3小时起.md | Y | ok |
| Y | positive | 82.0 | 50.0 | 狩猎 | 10 韩国高分.md | Y | ok |
| Y | positive | 82.0 | 83.0 | 盗火线 Heat | 03 帮派犯罪.md | Y | ok |
| Y | positive | 82.0 | 82.5 | 看不见的客人 Contratiempo | 08 经典高分.md | Y | ok |
| Y | positive | 82.0 | 62.3 | 碟中谍8最终清算 | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 52.3 | 福禄双霸天 The Blues Brothers | 11 音乐.md | Y | ok |
| Y | positive | 82.0 | 66.5 | 秘密特工 The Man from U.N.C.L.E. | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 83.0 | 童年往事 | 02 华语.md | Y | ok |
| Y | positive | 82.0 | 81.1 | 背靠背，脸对脸 | 02 华语.md | Y | ok |
| Y | positive | 82.0 | 81.1 | 芬奇 | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 90.1 | 茶馆 | 02 华语.md | Y | ok |
| Y | positive | 82.0 | 80.2 | 血钻 | 12 人物传记真实改编.md | Y | ok |
| Y | positive | 82.0 | 71.6 | 遥望南方的童年 | 02 华语.md | Y | ok |
| Y | positive | 82.0 | 62.3 | 金刚 | 09 超长3小时起.md | Y | ok |
| Y | positive | 82.0 | 83.0 | 银河护卫队 Guardians of the Galaxy | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 63.5 | 闪电侠 The Flash | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 71.2 | 阿丽塔战斗天使 | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 83.0 | 阿凡达 Avatar | 01 动作科幻无脑.md | Y | ok |
| Y | positive | 82.0 | 82.3 | 雨中曲 Singin’ in the Rain | 11 音乐.md | Y | ok |
| Y | positive | 82.0 | 83.9 | 雷米奇遇记 (Rémi sans famille) | 06 治愈坚韧勇敢.md | Y | ok |
| Y | positive | 82.0 | 63.9 | 音乐救赎者 | 11 音乐.md | Y | ok |
| Y | positive | 82.0 | 73.4 | 骗中骗 | 03 帮派犯罪.md | Y | ok |
