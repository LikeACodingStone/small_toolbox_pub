# 最终 Prompt 列表：1789 条语法全量 Anki APKG 制作

这份列表用于从头复现当前项目的最终结果。最终目标不是样例包，而是把 `anki_build/anki_grammar_completed.csv` 中全部 1789 条语法做成可导入 Anki 的高质量选择题 APKG。

## 1. 查看项目和确认目标

```text
显示所有项目
```

目标：
- 找到当前项目目录和已有输出。
- 确认最终输出目录使用 `anki_build/mcq_nanami_all/`。
- 不再使用旧的机械全量包作为最终结果。

## 2. 基于最新规则生成全部语法 APKG

```text
现在基于最新规则。帮我把所有语法文件都生成apkg
```

目标：
- 所有语法都要生成 APKG。
- 不只生成 TSV、HTML 或中间文件。
- 最终必须有总包和分级包。

## 3. 按示例包规则制作选择题

```text
我要你做成类似 anki_grammar_sample_10_mcq_nanami_mp3.apkg 的文件，完全按照这个里面设定的规则
```

目标：
- 使用类似样例包的卡片结构。
- 每张卡片包含语法点、中文含义、接续、解释、4 个日语选项、正确答案、每个选项的中文解析。
- 使用 Nanami MP3 音频。

## 4. 补全所有“待补”

```text
为什么里面有很多的待补，你能全部补上吗
```

目标：
- 最终 TSV 和 APKG 内不能出现 `待补`。
- 缺失的含义、说明、接续、例句、解析都要补齐。

## 5. 修正之前单独 APKG 的“待补”

```text
我要你继续把之前单独apkg也给我去掉待补
```

目标：
- 分级包和总包都不能有 `待补`。
- 不能只修总包。

## 6. 去掉例句/选项自动播放

```text
你帮我重新生成一下，就是去掉所有例句的自动播放功能
```

目标：
- 语法点主音频可以保留 `[sound:xxx.mp3]`。
- 选项/例句音频不能使用 `[sound:xxx.mp3]`，避免 Anki 自动播放。
- 选项/例句音频使用手动控件：

```html
<audio controls preload="none" src="xxx.mp3"></audio>
```

验收：
- 全量 TSV 中 `[sound:]` 总数应等于 1789，且都只对应 grammar 音频。
- 手动音频控件数应为 7156，也就是 1789 张卡 * 4 个选项。

## 7. 清理中间文件并保留说明

```text
帮我去掉这个项目里面所有和最终结果不相关的中间文件，另外，如果要从头开始到最终结果，请你基于我所有的对话记录，写一个完整的promt列表，markdown格式的
```

目标：
- 保留最终 APKG、必要源数据、生成脚本和说明文档。
- 删除旧的、误导性的、与最终结果无关的中间结果。
- 写出本文件 `FINAL_PROMPT_LIST.md`。

## 8. 解释 all grammar 和 mcq_nanami_all 的区别

```text
all grammer 和 mcq_nanami_all 有什么区别
```

结论：
- `all grammar` 通常指旧的全量语法资料或旧输出概念。
- `mcq_nanami_all` 是当前最终输出目录，存放全量高质量选择题 APKG、分级 APKG、TSV、预览 HTML 和音频素材。

## 9. 解释保留的 Python 文件

```text
为什么这个里面又很多的py文件，有什么作用
keep this four, and then write the explaination for this four py file in .md file
```

目标：
- 项目根目录保留 4 个 Python 文件。
- 在 `PY_FILE_EXPLANATION.md` 中解释每个文件的作用。

## 10. 纠正低质量机械选择题

```text
这个里面都是这种非常敷衍的例句，没有任何作用啊

基于这个需求和示例帮我从新制作所有的apkg文件，最后修正promt文件
```

目标：
- 不能生成 `ておくに`、`ておくを`、`ていくに`、`ていくを` 这种机械拼接错项。
- 4 个选项必须是自然日语句子。
- 错项要错在真实学习点上，例如接续、语义、语境、相近语法混淆。
- 错项不能只是和题目无关的自然句。A/B/C/D 必须围绕同一个知识点、相近表达或该表达的不恰当用法来形成干扰。
- 例如“い形容詞”不能只让正确项出现“い形容詞”，而应让四个选项都在判断词类：`おいしい`、`静か`、`行く`、`学生` 等。
- 这条规则必须应用到全部 1789 张卡，不能只修截图或样例卡。
- 正确例句必须真的符合语法点；不能用万能模板把语法点硬塞进句子。
- 如果源数据是 OCR 噪声且无法可靠解析，不要伪造日语例句；应改成表达识别题或使用源表中真实可用的括号例句。
- 背面要解释每个选项为什么对或错。

## 11. 纠正“只做样例”的错误

```text
不是，你在逗我吗，为什么卡片的数量只有6张，总包只有22张，我需要这个1789所有的语法的卡片，但是灵活的选择题，这个才是我的目的
继续跑这个项目
```

最终要求：
- 总包必须是 1789 张卡，不是 6 张、10 张、12 张或 22 张样例。
- 样例规则只能作为质量参考，不能替代全量生成。
- 全量生成脚本必须读取 `anki_build/anki_grammar_completed.csv` 的全部 1789 行。

## 12. 最终生成命令

```text
python create_anki_curated_quality_mcq_nanami.py
```

最终输出目录：

```text
anki_build/mcq_nanami_all/
```

最终 APKG：

```text
anki_grammar_all_mcq_nanami_mp3.apkg
anki_grammar_Minna_quality_mcq_nanami_mp3.apkg
anki_grammar_N2_quality_mcq_nanami_mp3.apkg
anki_grammar_N3_quality_mcq_nanami_mp3.apkg
anki_grammar_N5-N4_quality_mcq_nanami_mp3.apkg
```

## 13. 最终验收标准

必须全部满足：

- 总包 `notes=1789`，`cards=1789`，`media=8945`。
- 分包：
  - Minna: 167 张，835 个媒体。
  - N2: 618 张，3090 个媒体。
  - N3: 669 张，3345 个媒体。
  - N5-N4: 335 张，1675 个媒体。
- `anki_build/mcq_nanami_all/media/` 中应有 8945 个 MP3。
- 没有 0 字节 MP3。
- 全量 TSV/APKG 不包含 `待补`。
- 不包含机械错项 `ておくに`、`ておくを`、`ていくに`、`ていくを`。
- 选项音频不自动播放：选项字段不使用 `[sound:]`，而是手动 `<audio controls preload="none">`。
- 每张卡都有 4 个自然日语选项和中文解析。

## 当前最终结果说明

当前最终结果是“1789 条全量语法 + 灵活自然选择题 + Nanami MP3 + 选项手动播放”的 APKG 包。旧样例包和旧机械全量包只作为历史参考，不是最终交付物。
