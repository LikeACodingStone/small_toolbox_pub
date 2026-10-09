from __future__ import annotations

import csv
import hashlib
import html
import random
import re
from pathlib import Path

import genanki


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "anki_build"
SOURCE = OUT_DIR / "anki_grammar_cleaned_enriched.csv"


POINTS = [
    {
        "point": "～ あげく(に)",
        "connection": "動詞た形 / 名詞+の + あげく(に)",
        "cn": "经过多次讨论后，最后取消了计划。",
        "options": [
            ("何度も話し合った（あげく）、計画を中止した。", True, "正确：前面接动词た形，且后项是经过反复后的结果。"),
            ("何度も話し合う（あげく）、計画を中止した。", False, "错误：あげく前面通常接动词た形或名詞+の。"),
            ("何度も話し合った（あげくで）、計画を中止した。", False, "错误：固定形式是あげく/あげくに，不接で。"),
            ("少し話し合った（あげく）、すぐ計画を決めた。", False, "错误：あげく通常表示长时间、反复之后的结果，这里语义不自然。"),
        ],
    },
    {
        "point": "～ あまり(に)",
        "connection": "動詞普通形 / い形容詞 / な形容詞+な / 名詞+の + あまり(に)",
        "cn": "因为太高兴，眼泪流了出来。",
        "options": [
            ("うれしさの（あまり）、涙が出た。", True, "正确：名词化后的情感词接のあまり。"),
            ("うれしさ（あまり）、涙が出た。", False, "错误：名词接续时需要の。"),
            ("うれしさの（あまりで）、涙が出た。", False, "错误：这里不用あまりで。"),
            ("うれしさを（あまり）、涙が出た。", False, "错误：不能用を连接あまり。"),
        ],
    },
    {
        "point": "～ 以上(は)",
        "connection": "動詞普通形 / 名詞+である + 以上(は)",
        "cn": "既然约好了，就应该做到最后。",
        "options": [
            ("約束した（以上）、最後までやるべきだ。", True, "正确：既然已经约定，后项表达义务或判断。"),
            ("約束した（以上で）、最後までやるべきだ。", False, "错误：表示既然时不用以上で。"),
            ("約束した（以上に）、最後までやるべきだ。", False, "错误：以上に表示超过某程度，不是既然。"),
            ("約束した（以上から）、最後までやるべきだ。", False, "错误：没有以上から这种接法。"),
        ],
    },
    {
        "point": "～ 上で(は)",
        "connection": "動詞た形 / 名詞+の + 上で",
        "cn": "请在确认内容之后签名。",
        "options": [
            ("内容を確認した（上で）、署名してください。", True, "正确：動詞た形+上で表示先做前项，再做后项。"),
            ("内容を確認して（上で）、署名してください。", False, "错误：表示先后顺序时应接動詞た形。"),
            ("内容を確認した（上に）、署名してください。", False, "错误：上に表示而且/加之，不适合这里的先后顺序。"),
            ("内容を確認した（上でに）、署名してください。", False, "错误：上で后面不再接に。"),
        ],
    },
    {
        "point": "～ うちに",
        "connection": "動詞普通形 / い形容詞 / な形容詞+な / 名詞+の + うちに",
        "cn": "趁还没忘，我先记下来。",
        "options": [
            ("忘れない（うちに）、メモしておきます。", True, "正确：表示趁着还没有忘记的时候做后项。"),
            ("忘れた（うちに）、メモしておきます。", False, "错误：已经忘了就不能表示趁还没忘。"),
            ("忘れない（うちで）、メモしておきます。", False, "错误：表示期间内做某事用うちに。"),
            ("忘れない（うちを）、メモしておきます。", False, "错误：没有うちを这种接法。"),
        ],
    },
    {
        "point": "～ おかげで/おかげだ",
        "connection": "動詞普通形 / い形容詞 / な形容詞+な / 名詞+の + おかげで",
        "cn": "多亏老师，我通过了考试。",
        "options": [
            ("先生の（おかげで）、試験に合格できました。", True, "正确：名词接の，后项是好的结果。"),
            ("先生（おかげで）、試験に合格できました。", False, "错误：名词后需要の。"),
            ("先生の（おかげに）、試験に合格できました。", False, "错误：表示原因结果时用おかげで。"),
            ("先生を（おかげで）、試験に合格できました。", False, "错误：不能用を连接おかげで。"),
        ],
    },
    {
        "point": "～ 恐れがある",
        "connection": "動詞辞書形 / 名詞+の + 恐れがある",
        "cn": "由于台风，电车有可能停运。",
        "options": [
            ("台風で電車が止まる（恐れがある）。", True, "正确：前面接动词辞书形，表示不好的可能性。"),
            ("台風で電車が止まった（恐れがある）。", False, "错误：表示将来可能发生时通常接辞书形。"),
            ("台風で電車が止まる（恐れをある）。", False, "错误：固定形式是恐れがある。"),
            ("台風で電車が止まる（恐れがいる）。", False, "错误：不能把ある换成いる。"),
        ],
    },
    {
        "point": "～ からいうと/からいえば/からいったら/からいって",
        "connection": "名詞 + からいうと / からいえば / からいったら",
        "cn": "从经验来说，这个方法最安全。",
        "options": [
            ("経験（からいうと）、この方法が一番安全だ。", True, "正确：名词+からいうと表示从某角度判断。"),
            ("経験（からいうに）、この方法が一番安全だ。", False, "错误：没有からいうに这种形式。"),
            ("経験（からいってで）、この方法が一番安全だ。", False, "错误：からいって后面不接で。"),
            ("経験（からいうと）、昨日は早く寝た。", False, "错误：后项应是从该角度得出的判断，这里语义不成立。"),
        ],
    },
    {
        "point": "～ からといって",
        "connection": "普通形 + からといって",
        "cn": "虽说便宜，也不应该买不需要的东西。",
        "options": [
            ("安い（からといって）、必要ないものを買うべきではない。", True, "正确：表示不能仅以前项为理由就得出后项。"),
            ("安い（からといえば）、必要ないものを買うべきではない。", False, "错误：からといえば是说到/从...来说，不表示虽说也不能。"),
            ("安い（からといったら）、必要ないものを買うべきではない。", False, "错误：といったら用于强调或话题，不适合这里。"),
            ("安い（からといってで）、必要ないものを買うべきではない。", False, "错误：からといって后面不接で。"),
        ],
    },
    {
        "point": "～ ざるを得ない",
        "connection": "動詞ない形去ない + ざるを得ない",
        "cn": "因为雨变大了，不得不中止比赛。",
        "options": [
            ("雨が強くなったので、試合を中止せ（ざるを得なかった）。", True, "正确：する的ざる形式是せざる。"),
            ("雨が強くなったので、試合を中止し（ざるを得なかった）。", False, "错误：する要变成せざるを得ない。"),
            ("雨が強くなったので、試合を中止せ（ざるを得ないでした）。", False, "错误：过去式应放在得ない上，变成得なかった。"),
            ("雨が強くなったので、試合を中止せ（ざるを得なかっただ）。", False, "错误：得なかった后面不能接だ。"),
        ],
    },
]


FIELDS = [
    "CardID",
    "Level",
    "GrammarPoint",
    "GrammarPointTTS",
    "MeaningCN",
    "ExplanationCN",
    "Connection",
    "OptionA",
    "OptionATTS",
    "OptionB",
    "OptionBTTS",
    "OptionC",
    "OptionCTTS",
    "OptionD",
    "OptionDTTS",
    "CorrectOption",
    "CorrectExample",
    "CorrectExampleCN",
    "Rationale",
    "Source",
    "Tags",
]


FRONT_TEMPLATE = r"""
<div class="card-wrap">
  <div class="topline">
    <span class="level">{{Level}}</span>
  </div>

  <div class="audio-panel">
    <span class="audio-label">语法音频</span>
    {{tts ja_JP:GrammarPointTTS}}
  </div>

  <div class="grammar">{{GrammarPoint}}</div>

  <div class="choices">
    <div class="choice"><span class="letter">A</span><span>{{OptionA}}</span><span class="speaker">{{tts ja_JP:OptionATTS}}</span></div>
    <div class="choice"><span class="letter">B</span><span>{{OptionB}}</span><span class="speaker">{{tts ja_JP:OptionBTTS}}</span></div>
    <div class="choice"><span class="letter">C</span><span>{{OptionC}}</span><span class="speaker">{{tts ja_JP:OptionCTTS}}</span></div>
    <div class="choice"><span class="letter">D</span><span>{{OptionD}}</span><span class="speaker">{{tts ja_JP:OptionDTTS}}</span></div>
  </div>
</div>
"""

BACK_TEMPLATE = r"""
{{FrontSide}}
<hr class="divider">
<div class="answer">
  <div class="correct">正确答案：{{CorrectOption}}</div>
  <div class="meaning">{{MeaningCN}}</div>
  <div class="block"><b>正确例句</b><br>{{CorrectExample}}<br><span class="cn">{{CorrectExampleCN}}</span></div>
  <div class="block"><b>选项解析</b><br>{{Rationale}}</div>
  <div class="block"><b>接续</b><br>{{Connection}}</div>
  <div class="block"><b>解释</b><br>{{ExplanationCN}}</div>
  <div class="source">{{Source}}</div>
</div>
"""

CSS = r"""
.card {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans JP", "Microsoft YaHei", sans-serif;
  background: #f7f7f4;
  color: #1f2328;
  font-size: 20px;
  line-height: 1.55;
  text-align: left;
}
.card-wrap, .answer {
  max-width: 820px;
  margin: 0 auto;
  padding: 18px 20px;
}
.topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.level {
  background: #23395d;
  color: #fff;
  border-radius: 6px;
  padding: 3px 9px;
  font-size: 14px;
  font-weight: 700;
}
.hint, .source {
  color: #68707d;
  font-size: 13px;
}
.audio-panel {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #d8d5ca;
  border-radius: 6px;
  padding: 6px 9px;
  background: #fff;
  margin-bottom: 14px;
}
.audio-label {
  color: #59606b;
  font-size: 13px;
}
.grammar {
  font-size: 34px;
  font-weight: 800;
  letter-spacing: 0;
  margin: 8px 0 18px;
}
.choices {
  display: grid;
  gap: 10px;
}
.choice {
  display: grid;
  grid-template-columns: 36px 1fr auto;
  align-items: center;
  gap: 12px;
  background: #fff;
  border: 1px solid #dedbd2;
  border-left: 4px solid #6a8caf;
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 22px;
}
.letter {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #23395d;
  color: #fff;
  font-size: 16px;
  font-weight: 800;
}
.speaker {
  min-width: 40px;
  text-align: right;
}
.divider {
  border: 0;
  border-top: 1px solid #d8d5ca;
  max-width: 820px;
}
.correct {
  font-size: 26px;
  font-weight: 800;
  color: #1f5f3f;
  margin-bottom: 10px;
}
.meaning {
  font-size: 28px;
  font-weight: 800;
  color: #7b2d26;
  margin-bottom: 14px;
}
.block {
  background: #fff;
  border: 1px solid #dedbd2;
  border-radius: 6px;
  padding: 12px 14px;
  margin: 10px 0;
}
.cn {
  color: #59606b;
}
"""


def strip_parentheses_for_tts(value: str) -> str:
    value = re.sub(r"（[^）]*）", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"、{2,}", "、", value)
    return value.strip(" 、。") + ("。" if value.strip() and not value.strip().endswith("。") else "")


def load_source_rows() -> dict[str, dict[str, str]]:
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as fh:
        return {row["CleanGrammarPoint"]: row for row in csv.DictReader(fh)}


def build_rows() -> list[dict[str, str]]:
    source = load_source_rows()
    rows = []
    letters = ["A", "B", "C", "D"]
    for idx, item in enumerate(POINTS, start=1):
        base = source[item["point"]]
        rng = random.Random(idx * 20260711)
        options = list(item["options"])
        rng.shuffle(options)
        correct_index = next(index for index, option in enumerate(options) if option[1])
        correct_letter = letters[correct_index]
        correct_example = options[correct_index][0]
        rationale = "<br>".join(f"{letter}. {note}" for letter, (_, _, note) in zip(letters, options))

        row = {
            "CardID": f"JP-GRAMMAR-MCQ-SAMPLE-{idx:02d}",
            "Level": base["Level"],
            "GrammarPoint": base["CleanGrammarPoint"],
            "GrammarPointTTS": strip_parentheses_for_tts(base["CleanGrammarPoint"].replace("～", "")),
            "MeaningCN": base["MeaningCN"],
            "ExplanationCN": base["ExplanationCN"],
            "Connection": item["connection"],
            "CorrectOption": correct_letter,
            "CorrectExample": correct_example,
            "CorrectExampleCN": item["cn"],
            "Rationale": rationale,
            "Source": f"{base['Book']} / {base['SourcePageImage']}",
            "Tags": f"jp_grammar sample mcq {base['Level'].replace('/', '_')} auto_tts",
        }
        for letter, option in zip(letters, options):
            row[f"Option{letter}"] = option[0]
            row[f"Option{letter}TTS"] = strip_parentheses_for_tts(option[0])
        rows.append(row)
    return rows


def write_tsv(rows: list[dict[str, str]]) -> Path:
    path = OUT_DIR / "anki_grammar_sample_10_mcq.tsv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        fh.write("#separator:tab\n")
        fh.write("#html:true\n")
        fh.write("#deck:JP Grammar Sample 10 MCQ\n")
        writer = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_apkg(rows: list[dict[str, str]]) -> Path:
    model = genanki.Model(
        1707112036,
        "JP Grammar MCQ TTS Sample",
        fields=[{"name": field} for field in FIELDS],
        templates=[
            {
                "name": "Grammar MCQ",
                "qfmt": FRONT_TEMPLATE,
                "afmt": BACK_TEMPLATE,
            }
        ],
        css=CSS,
    )
    deck = genanki.Deck(1707112037, "JP Grammar Sample 10 MCQ")
    for row in rows:
        deck.add_note(
            genanki.Note(
                model=model,
                fields=[row[field] for field in FIELDS],
                tags=row["Tags"].split(),
                guid=hashlib.sha1(row["CardID"].encode("utf-8")).hexdigest(),
            )
        )
    path = OUT_DIR / "anki_grammar_sample_10_mcq_auto_tts.apkg"
    genanki.Package(deck).write_to_file(str(path))
    return path


def write_preview(rows: list[dict[str, str]]) -> Path:
    path = OUT_DIR / "anki_grammar_sample_10_mcq_preview.html"
    css = CSS.replace(".card {", "body {").replace(".card-wrap, .answer {", ".preview-card {")
    cards = []
    for row in rows:
        choices = "\n".join(
            f'<div class="choice"><span class="letter">{letter}</span><span>{html.escape(row[f"Option{letter}"])}</span><span class="speaker">TTS</span></div>'
            for letter in "ABCD"
        )
        cards.append(
            f"""
<section class="preview-card">
  <div class="topline"><span class="level">{html.escape(row['Level'])}</span><span class="hint">选择最符合该语法的例句</span></div>
  <div class="grammar">{html.escape(row['GrammarPoint'])}</div>
  <div class="choices">{choices}</div>
  <div class="correct">正确答案：{html.escape(row['CorrectOption'])}</div>
  <div class="meaning">{html.escape(row['MeaningCN'])}</div>
</section>"""
        )
    with path.open("w", encoding="utf-8-sig") as fh:
        fh.write('<!doctype html><html><head><meta charset="utf-8"><title>Anki Grammar MCQ Sample</title><style>')
        fh.write(css)
        fh.write(".preview-card{background:#f7f7f4;border:1px solid #dedbd2;border-radius:8px;margin:18px auto;max-width:820px;padding:18px 20px;}")
        fh.write("</style></head><body>")
        fh.write("\n".join(cards))
        fh.write("</body></html>")
    return path


def write_template() -> Path:
    path = OUT_DIR / "anki_grammar_sample_10_mcq_template.html"
    with path.open("w", encoding="utf-8-sig") as fh:
        fh.write("<!-- Front Template -->\n")
        fh.write(FRONT_TEMPLATE.strip())
        fh.write("\n\n<!-- Back Template -->\n")
        fh.write(BACK_TEMPLATE.strip())
        fh.write("\n\n<!-- Styling -->\n<style>\n")
        fh.write(CSS.strip())
        fh.write("\n</style>\n")
    return path


def main() -> None:
    rows = build_rows()
    for path in [write_apkg(rows), write_tsv(rows), write_template(), write_preview(rows)]:
        print(path)


if __name__ == "__main__":
    main()
