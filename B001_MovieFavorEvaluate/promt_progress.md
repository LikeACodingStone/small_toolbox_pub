# Prompt 变更过程梳理

这份文档记录本项目从最初的数据整理，到评分系统、反馈闭环、自动回归、模板化初始化、加密数据库层的需求演进。这里的 “prompt” 指每一阶段你对 Codex 提出的工程目标、规则和约束，不是代码中的模型 system prompt。

## 1. 初始数据目标：区分正负电影与缺失测试集

最早的目标是整理 `movies_details` 里的电影数据，并与已有 JSON 片单做对比。

核心规则逐渐明确为：

- `movies_details/00 record.md` 是负向电影来源。
- `movies_details` 里除 `00 record.md` 以外的所有文件都是正向电影来源。
- 已经存在于正向 JSON 或负向 JSON 中的电影不应该再出现在测试列表里。
- 没有进入 JSON 的剩余电影要生成一个测试文本，供后续人工或自动验证。

这一阶段形成了 `missing_movies_for_test.txt` 的概念，也奠定了后续 “movies_details 是人工标签来源” 的基础。

## 2. 评分标准第一次明确：正向 100，负向不是 0

随后你把评分标准从普通推荐分数推进为更强的个性化锚点系统。

关键变化：

- 正向 JSON 中的电影全部视为 100 分锚点。
- 负向 JSON 中的电影不是全部 0 分，而是代表 50 分以下。
- 负向电影不是“烂片”，而是“有你接受不了的点”。
- 每一条正向/负向记录都应该附加一个核心原因，说明肯定或否定的关键。

这个阶段让项目从简单电影推荐工具，转向了“个人偏好校准系统”。

## 3. 数据格式统一：全部使用 JSON

你明确不希望用 `jsonl`，而是要所有持久化数据都用 JSON。

因此项目中形成了这些数据文件：

- `my_pos_movies.json`
- `my_neg_movies.json`
- `feedback.json`
- `taste_profile.json`
- 各类回归报告 JSON

这让数据更容易人工查看、整体备份和与数据库互转。

## 4. 安全要求：TMDb API Key 加密

你指出 `TMDB_API_KEY` 不能明文放在代码或数据文件中。

于是需求变成：

- 使用 AES 加密 TMDb API Key。
- 启动程序时输入口令解密。
- 支持通过环境变量传入口令，方便自动化测试。
- 口令不能硬编码进源码。

这个阶段产生了：

- `crypto_utils.py`
- `tmdb_api_key.enc.json`
- `MOVIE_TMDB_KEY_PASSWORD` 环境变量支持

## 5. 反馈闭环：每次评分后可记录真实反馈

之后你关心“现在每一步电影都会被记录 feedback 吗”。

实际方向被整理为：

- 每次评分后可以输入真实评分。
- 回车跳过则不记录。
- 输入真实评分后写入 `feedback.json`。
- feedback 会作为未来评分的历史锚点。

这一步让评分系统从静态锚点，进入可持续学习的反馈闭环。

## 6. 偏好维度扩展：类型倾向和导演加分

你进一步提出了更细的个人偏好：

- 奇幻、大场面科幻、灾难、魔幻、大型动作片，完成度不差时天然加分。
- 真实故事改编、人物传记、历史纪实改编天然加分。
- 刻画坚韧、勇敢、人性尊严，或深刻剖析情感关系天然加分。
- 恐怖片、纯商业片、悬疑烧脑、战争片、抽象艺术电影适当减分。
- 已经喜欢过的导演，其新片适当加分。

这些要求被写入 `taste_profile.json` 的 `taste_dimensions` 和 `learned_core_features` 中，成为评分 prompt 和权重判断的一部分。

## 7. 工程目录重构：code / data / test

你要求把工程分为：

- `code`
- `data`
- `test`

因此主程序、数据、测试脚本被拆分。这个阶段解决的是工程可维护性问题，而不是评分准确性问题。

形成的职责边界：

- `code` 放主逻辑和公共工具。
- `data` 放 JSON、加密 key、movies_details。
- `test` 放同步、批量评估、回归和报告。

## 8. 自动测试：从批量报告到真实回归

你先要求自动读取 `missing_movies_for_test.txt`，为每部电影生成评分报告。

随后你发现测试结果不符合预期，于是要求：

- 自动执行测试。
- 正向电影 90% 以上要跑到 80 分以上。
- 负向电影 90% 以上要跑到 65 分以下。
- 自动调参数。
- 每一轮都必须跑完整个测试集。
- 如果 10 轮后仍不达标，保留最好参数。

这一阶段产生了真正的回归调参器：

- `validate_missing_movies.py`
- 支持 `--restart`
- 支持 `--resume`
- 每部电影后保存报告
- 通过后自动停止
- 失败则保留最佳参数

后来你明确指出要基于 `missing_movies_for_test.txt`，不是基于已有 JSON 片单测试。于是回归对象被修正为 movies_details 中尚未进入 JSON 的那部分电影。

## 9. 真实回归执行与结果确认

你要求“不在乎很久，要真实回归”。

于是执行了完整真实回归：

- 测试集：74 部 missing 电影
- 正向：54 部
- 负向：20 部
- 通过标准：正向 >= 80，负向 <= 65
- 目标通过率：两组都 >= 90%

最终结果：

- 正向 50/54，通过率 92.6%
- 负向 18/20，通过率 90.0%
- 第一轮即通过
- 最佳参数为 `round_01_current_profile`

同时确认：

- `missing_movies_regression_tuning_report.json` 不参与正式评分。
- 它只是报告和恢复状态。
- 真正影响评分的是 `taste_profile.json`、正负 JSON、feedback、movies_details、TMDb 和 Ollama。

## 10. 对“测试是否泄露进评分”的澄清

你问过：回归报告是不是不再评分代码起作用。

结论是：

- 回归报告本身不会被 `evaluate.py` 读取。
- 但 `movies_details` 标签会参与评分校准。
- 因此对 missing 测试集来说不是纯盲测，因为这些电影本身来自人工分类的 `movies_details`。

由此明确了两个概念：

- “标签一致性回归”：验证已人工分类电影是否按标签方向给分。
- “盲测泛化回归”：未来需要禁用 movies_details 校准，只靠模型、TMDb、JSON 锚点和 feedback。

## 11. 文档化：从完整 prompt 到架构说明

你要求把搭建过程写成英文 Markdown，并画出文件功能架构图。

最初生成的是：

- `PROJECT_PROMPT_AND_ARCHITECTURE.md`

里面同时包含：

- 从零搭建工程的英文 prompt 步骤
- 架构图
- 文件职责
- 操作命令

后来你要求拆分：

- 架构和操作说明单独保留为英文。
- prompt 变更过程另写中文。
- 架构文档中不再包含 prompt 内容。

于是形成当前这两个文档：

- `PROJECT_ARCHITECTURE.md`
- `promt_progress.md`

## 12. 隐私和数据库方向讨论

你提出如果要隐藏电影名字，有哪些方式。

讨论出的方案包括：

- 不提交 `data` 和 `reports`。
- 全文件 AES 加密。
- 内部 ID 化，把电影名放到单独加密映射表。
- HMAC 标题匹配，避免明文去重。
- 存 TMDb ID 但注意它也可反查。
- 使用 BitLocker、VeraCrypt、文件权限等系统级保护。

随后你进一步问如果用数据库怎么做。

推荐方向变成：

- SQLite 作为本地数据库。
- 敏感字段 AES-GCM 加密。
- 标题使用 HMAC 做匹配键。
- 程序启动时输入主密码。
- 派生加密 key 和 HMAC key。
- JSON 暂时保留明文，数据库作为加密存储和迁移层。

## 13. 模板化工程：inition 初始化层

你提出要把这个工程做成通用模板，并新增：

- `code`
- `data`
- `test`
- `inition`

其中 `inition` 负责存放：

- `positive.txt`
- `negtive.txt`
- `tmdb_key.txt`
- `rules.txt`
- `EnvSetup/envsetup.py`

目标是让一个新用户只要填写初始化文本，就能自动生成：

- `my_pos_movies.json`
- `my_neg_movies.json`
- `taste_profile.json`
- 加密 TMDb key
- 加密数据库

这个阶段新增了：

- `inition/positive.txt`
- `inition/negtive.txt`
- `inition/rules.txt`
- `inition/tmdb_key.txt`
- `inition/README.md`
- `inition/EnvSetup/envsetup.py`

并且把现有正负 JSON 的标题整理到了初始化文本中。

## 14. 加密 SQLite 转换层

你要求：

- 数据库按加密方案存放。
- JSON 和明文仍然保留。
- `code` 下面添加 JSON 和 DB 互相转换脚本。
- 读出来的 JSON 仍然是明文。

因此新增：

- `code/secure_movie_db.py`
- `data/movie_favor_secure.db`
- `data/.movie_favor_db_session.json`

数据库设计包括：

- `movies`
- `aliases`
- `feedback`
- `settings`
- `json_files`

其中：

- `movies` 是规范化电影表。
- `aliases` 用 HMAC 做标题别名匹配。
- `feedback` 保存加密 feedback。
- `settings` 保存加密配置。
- `json_files` 保存完整 JSON 文件的加密快照，保证 JSON/DB 可以完整互转。

## 15. 测试 prompt 文件

你要求在 `test` 下建立 `fisrt_auto_just.md`，它不是代码，而是给 Codex 自己调试参数用的 prompt。

该文件描述：

- 总共几个循环。
- 正向通过分数。
- 负向通过分数。
- 正负通过率。
- 一个循环表示把所有电影完整运行一遍。
- 自动调整参数直到通过率达标。

同时新增：

- `positive_test.txt`
- `negitive_test.txt`

作为小型测试种子。

## 16. 当前状态总结

当前项目已经从一个本地电影评分脚本，演进成一个通用模板化工程：

- 支持明文 JSON 数据。
- 支持加密 TMDb key。
- 支持 feedback 闭环。
- 支持 movies_details 人工标签校准。
- 支持 missing movies 自动同步。
- 支持真实回归调参。
- 支持中断恢复。
- 支持加密 SQLite 存储层。
- 支持从 `inition` 文本文件初始化新项目。
- 支持 Codex 通过 Markdown prompt 执行自动调参工作流。

最重要的设计取舍是：

- 当前评分主路径仍然使用明文 JSON，保证可读、可调、稳定。
- 加密数据库是新增的存储和迁移层，还不是评分主路径。
- 回归报告不进入评分逻辑。
- movies_details 标签会进入评分逻辑，因此它是“人工标签校准”，不是盲测。

