# Python 文件说明

项目根目录当前保留 4 个 Python 文件。最终生成 APKG 时，主要使用第 1 个文件。

## 1. `create_anki_curated_quality_mcq_nanami.py`

这是当前最终主生成脚本。

作用：
- 读取 `anki_build/anki_grammar_completed.csv` 中全部 1789 条语法。
- 生成高质量日语选择题卡片。
- 对已有人工精选语法点使用更细的人工规则。
- 对其他语法点使用相关干扰项 fallback，避免机械拼接错项，也避免“只有正确项相关、其他选项无关”的无效选择题。
- fallback 的错项会尽量使用相近表达、错误接续、错误语义场景或同一词类判断来干扰。
- 全量生成时，1789 张卡都必须走这个规则；不能只修个别截图卡或样例卡。
- 正确项必须是真正对应语法点的例句；无法解析的 OCR 噪声条目不再伪造例句，而改为表达识别题。
- 生成 Nanami MP3 音频。
- 语法点主音频使用 `[sound:xxx.mp3]`。
- 选项/例句音频使用 `<audio controls preload="none">`，避免自动播放。
- 输出总包和分级包到 `anki_build/mcq_nanami_all/`。

主要输出：

```text
anki_build/mcq_nanami_all/anki_grammar_all_mcq_nanami_mp3.apkg
anki_build/mcq_nanami_all/anki_grammar_Minna_quality_mcq_nanami_mp3.apkg
anki_build/mcq_nanami_all/anki_grammar_N2_quality_mcq_nanami_mp3.apkg
anki_build/mcq_nanami_all/anki_grammar_N3_quality_mcq_nanami_mp3.apkg
anki_build/mcq_nanami_all/anki_grammar_N5-N4_quality_mcq_nanami_mp3.apkg
```

常用命令：

```text
python create_anki_curated_quality_mcq_nanami.py
```

快速结构测试可用：

```text
python create_anki_curated_quality_mcq_nanami.py --skip-audio
```

## 2. `create_anki_sample_10_mcq.py`

这是早期 10 条人工样例题脚本。

作用：
- 保存最初的选择题设计思路。
- 提供人工题目结构参考。
- 里面的样例可作为“自然选项、错误解析、语法混淆点”的参考。

注意：
- 它不是最终全量生成脚本。
- 最终 1789 条全量包不直接依赖它来输出 APKG。

## 3. `complete_anki_grammar_fields.py`

这是语法基础字段补全脚本。

作用：
- 生成或维护基础数据表：

```text
anki_build/anki_grammar_completed.csv
```

- 补全语法点的中文含义、说明、接续、例句等基础字段。
- 为最终主生成脚本提供源数据。

注意：
- 如果基础 CSV 丢失或需要重建，先运行它。
- 当前最终 APKG 使用的是已经补好的 `anki_grammar_completed.csv`。

## 4. `create_anki_sample_10_mcq_nanami_mp3.py`

这是早期 10 条样例 APKG + Nanami MP3 生成脚本。

作用：
- 保存早期 Nanami 音频和 APKG 模板尝试。
- 作为旧样例包的生成参考。

注意：
- 它不是当前最终主入口。
- 当前最终包已经由 `create_anki_curated_quality_mcq_nanami.py` 接管模板、音频和全量生成逻辑。

## 推荐工作流

如果要重新生成当前最终 APKG：

```text
python create_anki_curated_quality_mcq_nanami.py
```

如果基础字段表需要重建：

```text
python complete_anki_grammar_fields.py
python create_anki_curated_quality_mcq_nanami.py
```

最终验收时检查：
- 总包 1789 张。
- 总媒体 8945 个。
- 没有 `待补`。
- 没有机械错项。
- 选项音频不自动播放。
