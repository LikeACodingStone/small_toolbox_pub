from __future__ import annotations

import asyncio
import argparse
import csv
import hashlib
import html
import random
import re
from pathlib import Path

import edge_tts
import genanki

from create_anki_sample_10_mcq import POINTS, strip_parentheses_for_tts


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "anki_build"
EXPORT_DIR = OUT_DIR / "mcq_nanami_all"
MEDIA_DIR = EXPORT_DIR / "media"
VOICE = "ja-JP-NanamiNeural"
SOURCE = OUT_DIR / "anki_grammar_completed.csv"

ALL_APKG = EXPORT_DIR / "anki_grammar_all_mcq_nanami_mp3.apkg"
ALL_TSV = EXPORT_DIR / "anki_grammar_all_mcq_nanami_mp3.tsv"
PREVIEW = EXPORT_DIR / "anki_grammar_quality_mcq_nanami_preview.html"


CARDS = [
    {
        "level": "N5/N4",
        "point": "～ておく / とく",
        "meaning": "预先做；先准备好；保持某状态",
        "connection": "動詞て形 + おく / 口语缩约：ておく → とく",
        "explanation": "为了之后的目的预先完成某动作，或让某状态保持下去。重点是“事先准备/放着保持”。",
        "options": [
            ("旅行の前に、ホテルを予約しておく。", True, "正确：旅行前预先预约酒店，符合“事先准备”。"),
            ("昨日から雨が降っておく。", False, "错误：自然现象持续不用ておく，应说降っている。"),
            ("毎朝六時に起きておく。", False, "错误：习惯性动作不用ておく，应说起きる。"),
            ("駅に着いたら、友だちが待っておく。", False, "错误：表示某人正在等待不用ておく，应说待っている。"),
        ],
    },
    {
        "level": "N5/N4",
        "point": "～ていく",
        "meaning": "继续……下去；朝远离说话人的方向去",
        "connection": "動詞て形 + いく",
        "explanation": "表示动作或变化从现在向将来持续，也可表示动作朝远离说话人的方向移动。",
        "options": [
            ("これからも日本語の勉強を続けていく。", True, "正确：从现在开始继续学习下去，表示面向未来的持续。"),
            ("昨日、日本語の勉強を続けていく。", False, "错误：昨日是过去时间，不能表示从现在往未来持续。"),
            ("先生が教室に入っていく。", False, "错误：若说话人在教室里，老师进入教室是靠近说话人，应说入ってくる。"),
            ("窓が開けていく。", False, "错误：窗户不会主动“开着去”，这里应说開いている或開いていく要有变化语境。"),
        ],
    },
    {
        "level": "N5/N4",
        "point": "～てくる",
        "meaning": "……过来；逐渐变得……起来",
        "connection": "動詞て形 + くる",
        "explanation": "表示动作朝说话人方向来，或变化从过去到现在逐渐显现。",
        "options": [
            ("寒くなってきたので、コートを着た。", True, "正确：天气逐渐变冷，表示变化接近现在。"),
            ("これから寒くなってきます。", False, "错误：これから通常表示面向未来，应用寒くなっていきます。"),
            ("友だちは駅から遠くへ歩いてきた。", False, "错误：遠くへ表示远离说话人方向，应根据视点用歩いていった。"),
            ("毎日朝ご飯を食べてくる。", False, "错误：单纯习惯不表示方向或变化，不自然。"),
        ],
    },
    {
        "level": "N5/N4",
        "point": "～てある",
        "meaning": "已经……好了；人为动作留下的状态",
        "connection": "他動詞て形 + ある",
        "explanation": "表示某人事先做了某动作，其结果状态现在还保留着。常用于准备好的状态。",
        "options": [
            ("会議の資料はもうコピーしてある。", True, "正确：有人事先复印好资料，结果状态保留。"),
            ("会議の資料はもうコピーしている。", False, "错误：ている偏动作进行或习惯，不突出“已经准备好”。"),
            ("ドアが開けてある人がいる。", False, "错误：句子结构不成立；てある描述状态，不这样接人。"),
            ("雨が降ってある。", False, "错误：降る是不及物自然现象，不能用てある。"),
        ],
    },
    {
        "level": "N5/N4",
        "point": "～てしまう",
        "meaning": "……完；不小心/遗憾地……",
        "connection": "動詞て形 + しまう",
        "explanation": "表示动作完成，也常带有后悔、遗憾、意外等语气。",
        "options": [
            ("大切な書類をなくしてしまった。", True, "正确：丢了重要文件，带遗憾和后悔语气。"),
            ("大切な書類をなくしておいた。", False, "错误：ておく表示预先做，不能表示不小心丢失。"),
            ("大切な書類をなくしてみた。", False, "错误：てみる表示试着做，不适合“丢失重要文件”。"),
            ("大切な書類をなくしてある。", False, "错误：てある表示人为结果状态，不用于这种非意图的丢失。"),
        ],
    },
    {
        "level": "N5/N4",
        "point": "～てみる",
        "meaning": "试着……",
        "connection": "動詞て形 + みる",
        "explanation": "表示先尝试做某动作，看看结果如何。",
        "options": [
            ("この靴を履いてみてもいいですか。", True, "正确：试穿鞋子，符合“尝试做”。"),
            ("この靴を履いてある。", False, "错误：てある表示准备好的状态，不表示试穿。"),
            ("この靴を履いてしまってもいいですか。", False, "错误：てしまう有完成或后悔语气，不是试穿。"),
            ("この靴を履いていくてもいいですか。", False, "错误：ていく不能这样接てもいい。"),
        ],
    },
    {
        "level": "N4/N3",
        "point": "～ようになる",
        "meaning": "变得会……；逐渐变得……",
        "connection": "動詞辞書形 / ない形 + ようになる",
        "explanation": "表示能力、习惯或状态发生变化，强调变化结果。",
        "options": [
            ("毎日練習して、漢字が読めるようになった。", True, "正确：经过练习，能力发生变化。"),
            ("毎日練習して、漢字を読めるようにした。", False, "错误：ようにする强调努力使其实现，不是能力自然变化的结果。"),
            ("毎日練習して、漢字が読めることになった。", False, "错误：ことになる表示外部决定或结果，不表示能力变化。"),
            ("毎日練習して、漢字が読めるためになった。", False, "错误：ためになる表示有帮助，不表示变得会做。"),
        ],
    },
    {
        "level": "N4/N3",
        "point": "～ようにする",
        "meaning": "设法做到；努力养成……",
        "connection": "動詞辞書形 / ない形 + ようにする",
        "explanation": "表示有意识地努力，使某行为成为习惯或实现某状态。",
        "options": [
            ("健康のために、毎日野菜を食べるようにしている。", True, "正确：有意识地坚持吃蔬菜，表示努力养成习惯。"),
            ("健康のために、毎日野菜を食べるようになっている。", False, "错误：ようになっている不表示主动努力养成习惯。"),
            ("健康のために、毎日野菜を食べることになっている。", False, "错误：ことになっている表示规定或安排。"),
            ("健康のために、毎日野菜を食べるためにしている。", False, "错误：ためにしている结构不自然。"),
        ],
    },
    {
        "level": "N3",
        "point": "～ことにする",
        "meaning": "决定……",
        "connection": "動詞辞書形 / ない形 + ことにする",
        "explanation": "表示说话人或主语主动做出的决定。",
        "options": [
            ("来月からジムに通うことにした。", True, "正确：自己决定下个月开始去健身房。"),
            ("来月からジムに通うことになった。", False, "错误：ことになる偏外部决定或自然结果，不是自己主动决定。"),
            ("来月からジムに通うようになった。", False, "错误：ようになる表示习惯或能力变化。"),
            ("来月からジムに通うためにした。", False, "错误：ためにした不是表达“决定”的自然形式。"),
        ],
    },
    {
        "level": "N3",
        "point": "～ことになる",
        "meaning": "决定为……；结果变成……",
        "connection": "動詞辞書形 / ない形 + ことになる",
        "explanation": "表示由外部安排、规则或情况导致的决定或结果，不强调个人主动选择。",
        "options": [
            ("会議で、来月から新しい制度を始めることになった。", True, "正确：会议决定，属于外部安排。"),
            ("会議で、来月から新しい制度を始めることにした。", False, "错误：ことにした强调个人或主语主动决定。"),
            ("会議で、来月から新しい制度を始めるようにした。", False, "错误：ようにした表示设法做到或调整方式。"),
            ("会議で、来月から新しい制度を始めるためになった。", False, "错误：ためになった表示有帮助，不表示决定。"),
        ],
    },
    {
        "level": "N3",
        "point": "～ばかり",
        "meaning": "刚刚……；总是/净是……",
        "connection": "動詞た形 + ばかり / 名詞 + ばかり",
        "explanation": "接动词た形表示刚做完；接名词表示限定或偏向。",
        "options": [
            ("さっき昼ご飯を食べたばかりなので、まだお腹がすいていない。", True, "正确：た形+ばかり表示刚刚做完。"),
            ("さっき昼ご飯を食べるばかりなので、まだお腹がすいていない。", False, "错误：表示刚刚做完要用た形。"),
            ("さっき昼ご飯を食べてばかりなので、まだお腹がすいていない。", False, "错误：てばかり表示总是做某事，不表示刚刚做完。"),
            ("さっき昼ご飯を食べたところばかりなので、まだお腹がすいていない。", False, "错误：ところ和ばかり不能这样叠用。"),
        ],
    },
    {
        "level": "N3",
        "point": "～たことがある",
        "meaning": "曾经……过",
        "connection": "動詞た形 + ことがある",
        "explanation": "表示过去有过某种经历。",
        "options": [
            ("京都へ行ったことがあります。", True, "正确：た形+ことがある表示曾经有过经历。"),
            ("京都へ行くことがあります。", False, "错误：辞书形+ことがある表示有时会做，不是曾经经历。"),
            ("京都へ行ったことにします。", False, "错误：ことにする表示决定，不表示经历。"),
            ("京都へ行ったものがあります。", False, "错误：没有这种表达经历的形式。"),
        ],
    },
]


CORRECT_CN = {
    "～ておく / とく": "旅行前先预约酒店。",
    "～ていく": "今后也会继续学习日语。",
    "～てくる": "因为天气逐渐变冷了，所以穿了外套。",
    "～てある": "会议资料已经复印好了。",
    "～てしまう": "我把重要文件弄丢了。",
    "～てみる": "可以试穿这双鞋吗？",
    "～ようになる": "每天练习后，变得会读汉字了。",
    "～ようにする": "为了健康，我一直尽量每天吃蔬菜。",
    "～ことにする": "我决定从下个月开始去健身房。",
    "～ことになる": "会议决定从下个月开始实行新制度。",
    "～ばかり": "刚刚吃过午饭，所以还不饿。",
    "～たことがある": "我去过京都。",
}


FIELDS = [
    "CardID",
    "Level",
    "GrammarPoint",
    "GrammarAudio",
    "MeaningCN",
    "ExplanationCN",
    "Connection",
    "OptionA",
    "OptionAAudio",
    "OptionB",
    "OptionBAudio",
    "OptionC",
    "OptionCAudio",
    "OptionD",
    "OptionDAudio",
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
    {{GrammarAudio}}
  </div>
  <div class="grammar">{{GrammarPoint}}</div>
  <div class="choices">
    <div class="choice"><span class="letter">A</span><span>{{OptionA}}</span><span class="speaker">{{OptionAAudio}}</span></div>
    <div class="choice"><span class="letter">B</span><span>{{OptionB}}</span><span class="speaker">{{OptionBAudio}}</span></div>
    <div class="choice"><span class="letter">C</span><span>{{OptionC}}</span><span class="speaker">{{OptionCAudio}}</span></div>
    <div class="choice"><span class="letter">D</span><span>{{OptionD}}</span><span class="speaker">{{OptionDAudio}}</span></div>
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
.source {
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


def audio_name(card_id: str, slot: str) -> str:
    return f"{card_id.lower()}_{slot}.mp3"


def sound(name: str) -> str:
    return f"[sound:{name}]"


def manual_audio(name: str) -> str:
    return f'<audio controls preload="none" src="{html.escape(name, quote=True)}"></audio>'


def tagify(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z一-龯ぁ-んァ-ヶ]+", "_", value)
    return value.strip("_") or "unknown"


def deck_id_for(name: str) -> int:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()
    return 1_707_160_200 + (int(digest[:8], 16) % 100_000)


def load_source_rows() -> dict[str, dict[str, str]]:
    if not SOURCE.exists():
        return {}
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as fh:
        return {row["CleanGrammarPoint"]: row for row in csv.DictReader(fh)}


def source_row_list() -> list[dict[str, str]]:
    if not SOURCE.exists():
        return []
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def primary_expression(point: str) -> str:
    value = point.replace("〜", "～").replace("~", "～")
    value = re.sub(r"^～\s*", "", value)
    value = re.split(r"[/／]", value)[0]
    return value.strip(" .。・、") or point.strip("～ ")


def contains_japanese(value: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value))


def safe_tts_text(value: str, fallback: str = "文法音声。") -> str:
    value = value.replace("共i", "続").replace("接共i詞", "接続詞")
    value = re.sub(r"[^\u3040-\u30ff\u3400-\u9fffA-Za-z0-9。、ー・\s]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or fallback


def natural_generic_options(point: str, meaning: str, category: str) -> list[tuple[str, bool, str]]:
    expr = primary_expression(point)
    label = meaning or f"「{point}」的用法"
    category = category or "形式/用法"

    particle_examples = {
        "さん": ("田中（さん）は日本語の先生です。", "正确：さん接在人名后，表示礼貌称呼。"),
        "を": ("朝ご飯（を）食べました。", "正确：を标记动作的对象。"),
        "に": ("明日、学校（に）行きます。", "正确：に标记到达点或方向。"),
        "で": ("図書館（で）勉強します。", "正确：で标记动作发生的场所。"),
        "は": ("私（は）学生です。", "正确：は提示主题。"),
        "が": ("空（が）青いです。", "正确：が标记主语或新信息。"),
        "から": ("東京（から）来ました。", "正确：から表示起点，也可表示原因。"),
        "まで": ("五時（まで）待ちます。", "正确：まで表示时间或范围终点。"),
        "より": ("電車（より）バスのほうが安いです。", "正确：より用于比较基准。"),
        "と": ("友だち（と）映画を見ました。", "正确：と表示共同动作的对象。"),
        "も": ("私（も）行きます。", "正确：も表示同类追加。"),
        "や": ("机の上に本（や）ノートがあります。", "正确：や用于不完全列举。"),
        "の": ("走る（の）が好きです。", "正确：の可以把前面的内容名词化。"),
    }

    if expr in particle_examples:
        correct, correct_note = particle_examples[expr]
        distractors = [
            ("昨日は雨だったので、家にいました。", "错误：这是原因句，没有练习该助词的核心功能。"),
            ("駅に着いたら、友だちが待っていました。", "错误：这是时间场景，不是本题目标用法。"),
            ("毎朝六時に起きて、散歩しています。", "错误：这是习惯说明，不是该助词的目标功能。"),
        ]
        return [(correct, True, correct_note), *[(text, False, note) for text, note in distractors]]

    special_patterns: list[tuple[bool, str, str]] = [
        ("に従" in expr, f"計画（{expr}）、作業を進めます。", f"正确：{expr} 表示按照计划、规则或变化推进。"),
        ("に基" in expr or "をもと" in expr, f"調査結果（{expr}）、報告書を作成しました。", f"正确：{expr} 表示以前项为基础或依据。"),
        ("について" in expr, f"日本の文化（{expr}）、発表します。", f"正确：{expr} 表示话题或讨论对象。"),
        ("に対" in expr, f"学生の質問（{expr}）、丁寧に答えました。", f"正确：{expr} 表示动作或态度面向的对象。"),
        ("として" in expr, f"彼は代表（{expr}）、会議に出席しました。", f"正确：{expr} 表示身份、资格或立场。"),
        ("ため" in expr, f"試験に合格する（{expr}）、毎日復習しています。", f"正确：{expr} 表示目的。"),
        ("ようにする" in expr, f"健康のために、毎日野菜を食べる（{expr}）。", f"正确：{expr} 表示有意识地努力做到。"),
        ("ようになる" in expr, f"毎日練習して、漢字が読める（{expr}）。", f"正确：{expr} 表示能力或状态发生变化。"),
        ("ことにする" in expr, f"来月からジムに通う（{expr}）。", f"正确：{expr} 表示主语主动决定。"),
        ("ことになる" in expr, f"会議で、新しい制度を始める（{expr}）。", f"正确：{expr} 表示外部安排或自然结果。"),
        ("ばかり" in expr, f"さっき昼ご飯を食べた（{expr}）です。", f"正确：{expr} 可表示刚刚做完某事。"),
        ("ことがある" in expr, f"京都へ行った（{expr}）。", f"正确：{expr} 表示曾经有过某种经历。"),
    ]
    for matched, correct, correct_note in special_patterns:
        if matched:
            distractors = [
                ("昨日は雨だったので、家にいました。", "错误：这是原因关系，不是该语法点的核心用法。"),
                ("駅に着いたら、友だちが待っていました。", "错误：这是时间场景，不是本题目标语法。"),
                ("毎朝六時に起きて、散歩しています。", "错误：这是习惯说明，不能替代目标表达。"),
            ]
            return [(correct, True, correct_note), *[(text, False, note) for text, note in distractors]]

    if expr.startswith("て") or expr.startswith("で"):
        correct = f"旅行の前に、ホテルを予約し{expr}。"
        correct_note = f"正确：动词て形后接 {expr}，构成目标表达。"
        distractors = [
            ("旅行の前に、ホテルを予約するために電話しました。", "错误：这是目的表达，不是本题目标结构。"),
            ("旅行の前に、ホテルを予約したばかりです。", "错误：这是刚做完的表达，不一定符合目标语法。"),
            ("旅行の前に、ホテルを予約すればよかったです。", "错误：这是后悔/假设表达，不是目标结构。"),
        ]
        return [(correct, True, correct_note), *[(text, False, note) for text, note in distractors]]

    if expr.startswith("ない") or expr.startswith("ず"):
        correct = f"朝ご飯を食べ{expr}、学校へ行きました。"
        correct_note = f"正确：该句用 {expr} 表示否定或不做前项的状态。"
        distractors = [
            ("朝ご飯を食べたので、元気が出ました。", "错误：这是原因结果，不是目标否定表达。"),
            ("朝ご飯を食べてから、学校へ行きました。", "错误：这是先后顺序，不是否定表达。"),
            ("朝ご飯を食べるために、早く起きました。", "错误：这是目的表达，不是目标语法。"),
        ]
        return [(correct, True, correct_note), *[(text, False, note) for text, note in distractors]]

    if expr.startswith("に") or expr.startswith("を") or expr.startswith("から"):
        correct = f"経験（{expr}）、この方法が安全だと判断しました。"
        correct_note = f"正确：名词后接 {expr}，表示角度、依据、对象或范围等关系。"
        distractors = [
            ("経験があるので、この仕事に慣れています。", "错误：这是普通原因句，不是目标表达。"),
            ("経験を積むために、毎日練習しています。", "错误：这是目的表达，不是本题目标语法。"),
            ("経験があっても、油断してはいけません。", "错误：这是让步，不是目标表达。"),
        ]
        return [(correct, True, correct_note), *[(text, False, note) for text, note in distractors]]

    if expr.startswith("ば") or "ば" == expr:
        correct = f"時間があれ（{expr}）、一緒に行きましょう。"
        correct_note = f"正确：{expr} 用于表示条件。"
        distractors = [
            ("時間があるので、一緒に行きます。", "错误：这是原因，不是条件。"),
            ("時間があるのに、行きませんでした。", "错误：这是逆接，不是条件。"),
            ("時間があるために、準備しました。", "错误：这是目的或原因表达，不是条件。"),
        ]
        return [(correct, True, correct_note), *[(text, False, note) for text, note in distractors]]

    connection_hint = ""
    if "名詞" in category:
        connection_hint = "名词"

    scenarios = {
        "原因": (
            f"大雨（{expr}）、試合は中止になった。",
            "正确：前后是明确的原因和结果关系。",
            [
                ("駅に着いたら、友だちが待っていた。", "错误：这是到达后的场面描写，不是在表达原因结果。"),
                ("毎朝六時に起きて、散歩します。", "错误：这是习惯性动作，不符合该语法的原因功能。"),
                ("この料理は辛いですが、とてもおいしいです。", "错误：这是逆接评价，不是原因表达。"),
            ],
        ),
        "条件": (
            f"時間がある（{expr}）、一緒に行きましょう。",
            "正确：前项提出条件，后项是在该条件下成立的行为。",
            [
                ("昨日は時間があったので、一緒に行きました。", "错误：这是过去事实和原因，不是条件表达。"),
                ("時間があるのに、何もしません。", "错误：这是逆接语气，不是条件。"),
                ("時間があるところです。", "错误：这是状态说明，不能表达条件关系。"),
            ],
        ),
        "时间": (
            f"電車を待っている（{expr}）、友だちから電話が来た。",
            "正确：前项提供时间场景，后项在该时间发生。",
            [
                ("電車を待つために、駅へ行った。", "错误：这是目的表达，不是时间场景。"),
                ("電車を待ったから、疲れました。", "错误：这是原因结果，不是该语法的时间功能。"),
                ("電車を待てば、友だちから電話が来る。", "错误：这是条件句，语义不自然。"),
            ],
        ),
        "逆接": (
            f"値段は高い（{expr}）、品質はとてもいい。",
            "正确：前后内容形成转折或让步关系。",
            [
                ("値段が高いので、買いませんでした。", "错误：这是原因关系，不是逆接。"),
                ("値段が高ければ、品質もいいです。", "错误：这是条件判断，不是转折。"),
                ("値段が高くて、品質もいいです。", "错误：这是并列说明，不突出逆接。"),
            ],
        ),
        "让步": (
            f"雨が降る（{expr}）、予定どおり出発します。",
            "正确：即使前项成立，后项仍然成立，符合让步语义。",
            [
                ("雨が降ったので、出発をやめました。", "错误：这是原因结果，不是让步。"),
                ("雨が降る前に、出発しました。", "错误：这是时间先后，不是让步。"),
                ("雨が降りそうだから、傘を持っていきます。", "错误：这是原因和准备，不是让步。"),
            ],
        ),
        "目的": (
            f"試験に合格する（{expr}）、毎日復習している。",
            "正确：前项表示目的，后项是为达成目的而做的行为。",
            [
                ("試験に合格したので、家族が喜んだ。", "错误：这是原因结果，不是目的。"),
                ("試験に合格したところです。", "错误：这是刚完成的状态，不是目的。"),
                ("試験に合格しても、勉強を続けます。", "错误：这是让步，不是目的。"),
            ],
        ),
        "变化": (
            f"練習を続けて、日本語が話せる（{expr}）。",
            "正确：表达能力或状态发生变化。",
            [
                ("日本語を話すために、練習しています。", "错误：这是目的表达，不是变化结果。"),
                ("日本語が話せるから、通訳を頼まれた。", "错误：这是原因，不是变化。"),
                ("日本語を話したばかりです。", "错误：这是刚做完某动作，不是变化。"),
            ],
        ),
        "程度": (
            f"今日は歩きすぎて、足が痛い（{expr}）。",
            "正确：后项体现程度强烈或程度结果。",
            [
                ("今日は歩くために、早く起きた。", "错误：这是目的，不是程度。"),
                ("今日は歩いたら、友だちに会った。", "错误：这是时间/条件场景，不是程度。"),
                ("今日は歩くことにした。", "错误：这是决定，不是程度。"),
            ],
        ),
        "评价": (
            f"この映画は、もう一度見たい（{expr}）面白い。",
            "正确：该句表达说话人对事物的评价。",
            [
                ("この映画を見るために、映画館へ行った。", "错误：这是目的，不是评价。"),
                ("この映画を見たところ、友だちに会った。", "错误：这是场面/时间连接，不是评价。"),
                ("この映画を見なければ、分かりません。", "错误：这是条件，不是评价。"),
            ],
        ),
        "判断": (
            f"この結果（{expr}）、計画を見直す必要がある。",
            "正确：以前项为依据作出判断。",
            [
                ("この結果のために、資料を作った。", "错误：这是目的或原因，不是依据判断。"),
                ("この結果なのに、誰も驚かなかった。", "错误：这是逆接，不是判断依据。"),
                ("この結果になるように、練習した。", "错误：这是目的达成，不是判断。"),
            ],
        ),
        "说明": (
            f"つまり、予定が変わった（{expr}）です。",
            "正确：用于解释、概括或说明前后内容。",
            [
                ("予定が変わるために、電話しました。", "错误：这是目的表达，不是说明。"),
                ("予定が変わったのに、誰も連絡しなかった。", "错误：这是逆接，不是说明。"),
                ("予定が変われば、連絡します。", "错误：这是条件，不是说明。"),
            ],
        ),
        "列举": (
            f"週末は映画を見る（{expr}）、買い物をする（{expr}）して過ごします。",
            "正确：举出多个例子，符合列举功能。",
            [
                ("週末は映画を見るために、早く帰ります。", "错误：这是目的，不是列举。"),
                ("週末は映画を見たばかりです。", "错误：这是刚做完，不是列举。"),
                ("週末は映画を見るなら、予約してください。", "错误：这是条件建议，不是列举。"),
            ],
        ),
    }

    chosen_key = next((key for key in scenarios if key in category), None)
    if chosen_key:
        correct, correct_note, distractors = scenarios[chosen_key]
    else:
        if contains_japanese(expr) and len(expr) <= 20:
            correct = f"先生は黒板に「{expr}」を使った自然な例文を書きました。"
            correct_note = f"正确：该选项把“{label}”作为本题要确认的表达。"
        else:
            correct = "先生は新しい文法表現を使って、自然な例文を作りました。"
            correct_note = f"正确：该选项用于处理 OCR 中难以直接造句的条目“{label}”。"
        distractors = [
            ("駅に着いたら、友だちが待っていました。", "错误：这是普通场面描写，没有体现目标语法的功能。"),
            ("昨日は雨だったので、家にいました。", "错误：这是基础原因句，和本题目标表达不同。"),
            ("毎朝六時に起きて、散歩しています。", "错误：这是习惯说明，不符合本语法点的核心功能。"),
        ]

    return [(correct, True, correct_note), *[(text, False, note) for text, note in distractors]]


def natural_generic_options(point: str, meaning: str, category: str) -> list[tuple[str, bool, str]]:
    """Build related MCQ options when no hand-curated card exists.

    The distractors must test the same grammar point or close grammar choices.
    They should not be unrelated sentences that can be eliminated without knowing
    the target expression.
    """
    expr = primary_expression(point)
    signal = f"{point} {meaning or ''} {category or ''}"

    def pack(
        correct: str,
        correct_note: str,
        distractors: list[tuple[str, str]],
    ) -> list[tuple[str, bool, str]]:
        return [(correct, True, correct_note), *[(text, False, note) for text, note in distractors[:3]]]

    def close_form_options(
        frame: str,
        target: str,
        alternatives: list[tuple[str, str]],
        correct_note: str,
    ) -> list[tuple[str, bool, str]]:
        distractors = [(frame.format(x=form), note) for form, note in alternatives if form != target]
        while len(distractors) < 3:
            distractors.append((
                frame.format(x="こと"),
                "错误：这个形式和目标表达功能不同，放在该语境里不自然。",
            ))
        return pack(frame.format(x=target), correct_note, distractors)

    # OCR often turns grammar labels into noisy text. For word-class cards, all
    # options should still test the same word-class distinction.
    if "形容詞の" in signal or ("形容詞" in signal and "代替" in signal):
        return pack(
            "赤い（の）をください。",
            "正确：这里的「の」代替前面提到的名词，相当于“红色的那个”。",
            [
                ("赤い（こと）をください。", "错误：「こと」表示抽象事情，不能指代要买的具体物品。"),
                ("赤い（な）をください。", "错误：「な」不能这样接在い形容词后面代替名词。"),
                ("赤い（ため）をください。", "错误：「ため」表示目的或原因，不能代替名词。"),
            ],
        )

    if "な形容詞" in signal:
        return pack(
            "「静か」は（な形容詞）です。",
            "正确：「静か」は名词前接「な」的な形容词。",
            [
                ("「おいしい」は（な形容詞）です。", "错误：「おいしい」はい形容词，不是な形容词。"),
                ("「行く」は（な形容詞）です。", "错误：「行く」是动词，不是形容词。"),
                ("「学生」は（な形容詞）です。", "错误：「学生」是名词，不是な形容词。"),
            ],
        )

    if "い形容詞" in signal or "し形容詞" in signal or ("形容詞" in signal and "な形容詞" not in signal):
        label = "い形容詞" if "し形容詞" in expr else expr
        if len(label) > 12 or "形容詞" not in label:
            label = "い形容詞"
        return pack(
            f"「おいしい」は（{label}）です。",
            f"正确：「おいしい」以「い」结尾，可作为{label}使用。",
            [
                (f"「静か」は（{label}）です。", "错误：「静か」是な形容词，修饰名词时要用「静かな」。"),
                (f"「行く」は（{label}）です。", "错误：「行く」是动词，不是形容词。"),
                (f"「学生」は（{label}）です。", "错误：「学生」是名词，不是形容词。"),
            ],
        )

    particle_sets = {
        "さん": (
            "田中（さん）は日本語の先生です。",
            "正确：「さん」接在人名后，表示礼貌称呼。",
            [
                ("田中（を）は日本語の先生です。", "错误：「を」标记动作对象，不能用于礼貌称呼人名。"),
                ("田中（で）は日本語の先生です。", "错误：「で」表示场所或手段，不能接在人名后表示称呼。"),
                ("田中（から）は日本語の先生です。", "错误：「から」表示起点或原因，不表示礼貌称呼。"),
            ],
        ),
        "を": (
            "朝ご飯（を）食べました。",
            "正确：「を」标记动作「食べる」的对象。",
            [
                ("朝ご飯（に）食べました。", "错误：「に」表示方向、时间或对象，不能标记「食べる」的直接对象。"),
                ("朝ご飯（で）食べました。", "错误：「で」表示场所或手段，不能标记被吃的东西。"),
                ("朝ご飯（が）食べました。", "错误：「が」会把朝饭当成动作主语，语义不成立。"),
            ],
        ),
        "に": (
            "明日、学校（に）行きます。",
            "正确：「に」可标记移动的到达点。",
            [
                ("明日、学校（を）行きます。", "错误：「を」不能标记普通移动动词「行く」的到达点。"),
                ("明日、学校（で）行きます。", "错误：「で」表示动作发生场所，不表示到达方向。"),
                ("明日、学校（から）行きます。", "错误：「から」表示出发点，不是要去的目的地。"),
            ],
        ),
        "で": (
            "図書館（で）勉強します。",
            "正确：「で」标记动作发生的场所。",
            [
                ("図書館（に）勉強します。", "错误：「に」不用于标记「勉強する」这个动作发生的场所。"),
                ("図書館（を）勉強します。", "错误：「を」标记动作对象，不能标记学习地点。"),
                ("図書館（から）勉強します。", "错误：「から」表示起点，不能表示学习发生的场所。"),
            ],
        ),
        "は": (
            "私（は）学生です。",
            "正确：「は」提示主题。",
            [
                ("私（を）学生です。", "错误：「を」需要搭配动作动词，不能接在判断句主题后。"),
                ("私（で）学生です。", "错误：「で」不用于提示判断句主题。"),
                ("私（から）学生です。", "错误：「から」表示起点或原因，不表示主题。"),
            ],
        ),
        "が": (
            "空（が）青いです。",
            "正确：「が」标记状态或性质的主体。",
            [
                ("空（を）青いです。", "错误：「を」不能标记形容词谓语的主体。"),
                ("空（で）青いです。", "错误：「で」表示场所或手段，不表示性质主体。"),
                ("空（から）青いです。", "错误：「から」表示起点或原因，不能这样说明性质主体。"),
            ],
        ),
        "から": (
            "東京（から）来ました。",
            "正确：「から」表示出发点或起点。",
            [
                ("東京（まで）来ました。", "错误：「まで」表示终点，和「来ました」的出发点语义相反。"),
                ("東京（を）来ました。", "错误：「を」一般不标记「来る」的出发点。"),
                ("東京（で）来ました。", "错误：「で」表示场所或手段，不表示从哪里来。"),
            ],
        ),
        "まで": (
            "五時（まで）待ちます。",
            "正确：「まで」表示时间或范围的终点。",
            [
                ("五時（から）待ちます。", "错误：「から」表示起点，不是等待到五点为止。"),
                ("五時（で）待ちます。", "错误：「で」不能自然表示等待的终点。"),
                ("五時（を）待ちます。", "错误：「を」会把五点当动作对象，不表示期限。"),
            ],
        ),
        "より": (
            "電車（より）バスのほうが安いです。",
            "正确：「より」表示比较基准。",
            [
                ("電車（まで）バスのほうが安いです。", "错误：「まで」表示终点，不能作比较基准。"),
                ("電車（から）バスのほうが安いです。", "错误：「から」表示起点或原因，不表示比较基准。"),
                ("電車（で）バスのほうが安いです。", "错误：「で」表示场所或手段，不能构成比较。"),
            ],
        ),
        "と": (
            "友だち（と）映画を見ました。",
            "正确：「と」表示共同动作的对象。",
            [
                ("友だち（を）映画を見ました。", "错误：「を」会把朋友当动作对象，不能表示“一起”。"),
                ("友だち（で）映画を見ました。", "错误：「で」不能表示共同看电影的对象。"),
                ("友だち（から）映画を見ました。", "错误：「から」表示起点或来源，不表示共同动作。"),
            ],
        ),
        "も": (
            "私（も）行きます。",
            "正确：「も」表示同类追加，意思是“我也去”。",
            [
                ("私（を）行きます。", "错误：「を」不能标记「行く」的主语或追加对象。"),
                ("私（で）行きます。", "错误：「で」表示手段或场所，不表示“也”。"),
                ("私（から）行きます。", "错误：「から」表示起点，不表示同类追加。"),
            ],
        ),
        "や": (
            "机の上に本（や）ノートがあります。",
            "正确：「や」用于不完全列举。",
            [
                ("机の上に本（を）ノートがあります。", "错误：「を」不能连接列举的名词。"),
                ("机の上に本（で）ノートがあります。", "错误：「で」不用于名词列举。"),
                ("机の上に本（から）ノートがあります。", "错误：「から」表示起点，不能连接列举项。"),
            ],
        ),
        "の": (
            "走る（の）が好きです。",
            "正确：「の」可以把前面的动词短语名词化。",
            [
                ("走る（を）が好きです。", "错误：「を」不能把动词短语名词化。"),
                ("走る（で）が好きです。", "错误：「で」表示场所或手段，不能作名词化。"),
                ("走る（から）が好きです。", "错误：「から」表示原因或起点，不能作主语名词化。"),
            ],
        ),
    }
    if expr in particle_sets:
        correct, note, distractors = particle_sets[expr]
        return pack(correct, note, distractors)

    # Close grammar groups: every option is a plausible-looking expression in
    # the same sentence, but only the target expression fits the stated function.
    close_groups = [
        (("について", "に関して"), "日本の文化（{x}）、発表します。", [
            ("に対して", "错误：「に対して」表示面向某对象的动作或态度，不是单纯话题。"),
            ("によって", "错误：「によって」表示手段、原因或差异，不表示讨论话题。"),
            ("にとって", "错误：「にとって」表示从某人立场看，不表示话题。"),
        ], f"正确：{expr} 表示话题或讨论对象。"),
        (("に対",), "学生の質問（{x}）、丁寧に答えました。", [
            ("について", "错误：「について」表示话题，不表示回答所面向的对象。"),
            ("によって", "错误：「によって」表示手段或原因，不适合表示回答对象。"),
            ("にとって", "错误：「にとって」表示立场，不表示动作面向的对象。"),
        ], f"正确：{expr} 表示动作或态度面向的对象。"),
        (("に基", "をもと"), "調査結果（{x}）、報告書を作成しました。", [
            ("について", "错误：「について」表示话题，不表示依据。"),
            ("に対して", "错误：「に対して」表示对象，不表示以资料为基础。"),
            ("にとって", "错误：「にとって」表示立场，不表示依据。"),
        ], f"正确：{expr} 表示以前项为基础或依据。"),
        (("に従",), "規則（{x}）、手続きを進めてください。", [
            ("につれて", "错误：「につれて」表示随变化而变化，不表示按照规则。"),
            ("に伴って", "错误：「に伴って」表示伴随变化，不表示遵守规则。"),
            ("について", "错误：「について」表示话题，不表示按照规则行动。"),
        ], f"正确：{expr} 表示按照规则、指示或变化推进。"),
        (("につれて", "に伴"), "町の人口が増える（{x}）、店も多くなりました。", [
            ("に従って", "错误：「に従って」偏向按照规则或指示，不适合这里的自然伴随变化。"),
            ("について", "错误：「について」表示话题，不表示两个变化同步。"),
            ("に対して", "错误：「に対して」表示对象，不表示伴随变化。"),
        ], f"正确：{expr} 表示随着前项变化，后项也变化。"),
        (("として",), "彼は代表（{x}）、会議に出席しました。", [
            ("について", "错误：「について」表示话题，不表示身份资格。"),
            ("にとって", "错误：「にとって」表示立场，不表示作为某身份。"),
            ("によって", "错误：「によって」表示手段或原因，不表示身份。"),
        ], f"正确：{expr} 表示身份、资格或立场。"),
        (("ことにする",), "来月からジムに通う（{x}）。", [
            ("ことになる", "错误：「ことになる」多表示外部安排，不是说话人主动决定。"),
            ("ようになる", "错误：「ようになる」表示状态变化，不表示决定。"),
            ("ためにする", "错误：「ためにする」不是这里表示决定的自然形式。"),
        ], f"正确：{expr} 表示主语主动决定。"),
        (("ことになる",), "会議で、新しい制度を始める（{x}）。", [
            ("ことにする", "错误：「ことにする」表示主动决定，和会议安排的语气不同。"),
            ("ようにする", "错误：「ようにする」表示努力做到，不表示外部安排。"),
            ("つもりだ", "错误：「つもりだ」表示个人打算，不表示制度安排。"),
        ], f"正确：{expr} 表示外部安排或自然结果。"),
        (("ようにする",), "健康のために、毎日野菜を食べる（{x}）。", [
            ("ようになる", "错误：「ようになる」表示状态变化，不表示有意识地努力做到。"),
            ("ことになる", "错误：「ことになる」表示安排或结果，不表示个人习惯努力。"),
            ("ためになる", "错误：「ためになる」表示有帮助，不能接在这里表示努力。"),
        ], f"正确：{expr} 表示有意识地努力做到。"),
        (("ようになる",), "毎日練習して、漢字が読める（{x}）。", [
            ("ようにする", "错误：「ようにする」表示努力做到，不表示能力已经变化。"),
            ("ことにする", "错误：「ことにする」表示主动决定，不表示能力变化。"),
            ("ためにする", "错误：「ためにする」不是表示状态变化的形式。"),
        ], f"正确：{expr} 表示能力或状态发生变化。"),
        (("ばかり",), "さっき昼ご飯を食べた（{x}）です。", [
            ("ところ", "错误：「たところ」也可表示刚做完，但这里缺少与题目目标一致的表达。"),
            ("ことがある", "错误：「ことがある」表示经验，不表示刚刚做完。"),
            ("ため", "错误：「ため」表示原因或目的，不表示刚完成。"),
        ], f"正确：{expr} 可表示刚刚做完某事。"),
        (("ことがある",), "京都へ行った（{x}）。", [
            ("ばかりだ", "错误：「ばかりだ」表示刚做完，不表示曾经经验。"),
            ("ところだ", "错误：「ところだ」表示动作阶段，不表示过去经验。"),
            ("つもりだ", "错误：「つもりだ」表示打算，不表示经验。"),
        ], f"正确：{expr} 表示曾经有过某种经历。"),
    ]
    for keys, frame, alternatives, note in close_groups:
        if any(key in expr for key in keys):
            return close_form_options(frame, expr, alternatives, note)

    if expr.startswith("て") or expr.startswith("で"):
        alternatives = [
            ("ている", "错误：「ている」表示进行或状态，不一定表示预先准备。"),
            ("てしまう", "错误：「てしまう」强调完成或遗憾，不表示预先做准备。"),
            ("ていく", "错误：「ていく」表示变化持续或离开说话人方向，不表示预先准备。"),
            ("ておく", "错误：「ておく」表示预先做准备；若不是本题目标，就不能替代目标表达。"),
        ]
        return close_form_options(
            "旅行の前に、ホテルを予約し{x}。",
            expr,
            alternatives,
            f"正确：动词て形后接 {expr}，符合本题目标表达。",
        )

    if expr.startswith("ない") or expr.startswith("ず"):
        return close_form_options(
            "朝ご飯を食べ{x}、学校へ行きました。",
            expr,
            [
                ("てから", "错误：「てから」表示先后顺序，不是否定状态。"),
                ("たので", "错误：「たので」表示原因，不是否定表达。"),
                ("るために", "错误：「ために」表示目的，不表示不做前项。"),
            ],
            f"正确：{expr} 表示否定或不做前项的状态。",
        )

    if "原因" in signal or "因为" in signal or "由于" in signal:
        return close_form_options(
            "大雨（{x}）、試合は中止になった。",
            expr,
            [
                ("のに", "错误：「のに」表示逆接，后项不应是顺接结果。"),
                ("ために", "错误：「ために」常表示目的；用于原因时接续和语气要更谨慎。"),
                ("なら", "错误：「なら」表示条件或话题承接，不表示既定原因。"),
            ],
            f"正确：{expr} 在这里连接原因和结果。",
        )

    if "条件" in signal or "如果" in signal:
        return close_form_options(
            "時間がある（{x}）、一緒に行きましょう。",
            expr,
            [
                ("ので", "错误：「ので」表示原因，不提出条件。"),
                ("のに", "错误：「のに」表示逆接，不表示条件。"),
                ("ところ", "错误：「ところ」表示场面或阶段，不表示条件。"),
            ],
            f"正确：{expr} 用于提出条件。",
        )

    if "时间" in signal or "時" in signal or "とき" in signal:
        return close_form_options(
            "電車を待っている（{x}）、友だちから電話が来た。",
            expr,
            [
                ("ために", "错误：「ために」表示目的，不表示时间场景。"),
                ("から", "错误：「から」表示原因或起点，不能替代时间场景。"),
                ("なら", "错误：「なら」表示条件或话题，不表示正在发生的时间。"),
            ],
            f"正确：{expr} 表示前项提供时间场景。",
        )

    if "逆接" in signal or "虽然" in signal or "但是" in signal or "却" in signal:
        return close_form_options(
            "値段は高い（{x}）、品質はとてもいい。",
            expr,
            [
                ("ので", "错误：「ので」表示原因，不能表达转折。"),
                ("なら", "错误：「なら」表示条件，不突出前后反差。"),
                ("ために", "错误：「ために」表示目的或原因，不表示逆接。"),
            ],
            f"正确：{expr} 表示前后内容转折或让步。",
        )

    if "目的" in signal or "为了" in signal:
        return close_form_options(
            "試験に合格する（{x}）、毎日復習している。",
            expr,
            [
                ("ので", "错误：「ので」表示原因，不表示目的。"),
                ("ところ", "错误：「ところ」表示动作阶段，不表示目的。"),
                ("のに", "错误：「のに」表示逆接，不能表达目标。"),
            ],
            f"正确：{expr} 表示目的。",
        )

    if "变化" in signal or "变成" in signal or "ようになる" in expr:
        return close_form_options(
            "練習を続けて、日本語が話せる（{x}）。",
            expr,
            [
                ("ようにする", "错误：「ようにする」表示努力做到，不表示能力变化结果。"),
                ("ために", "错误：「ために」表示目的，不表示变化结果。"),
                ("ことにする", "错误：「ことにする」表示决定，不表示自然变化。"),
            ],
            f"正确：{expr} 表示能力或状态发生变化。",
        )

    # Last fallback: keep all choices in the same grammar decision. The target
    # expression is contrasted with common neighboring expressions, instead of
    # unrelated full sentences.
    if expr.startswith("に") or expr.startswith("を") or expr.startswith("から"):
        return close_form_options(
            "この問題（{x}）、みんなで話し合いました。",
            expr,
            [
                ("について", "错误：「について」只表示话题，和目标表达的接续或语义不同。"),
                ("に対して", "错误：「に対して」表示对象或态度面向，不能随意替代目标表达。"),
                ("によって", "错误：「によって」表示手段、原因或差异，不能随意替代目标表达。"),
            ],
            f"正确：{expr} 符合本题要求的接续和语义。",
        )

    return close_form_options(
        "先生は例文の空欄に（{x}）を入れて、文の意味を確認しました。",
        expr,
        [
            ("について", "错误：这是相近表达之一，但接续或语义不符合本题目标。"),
            ("ために", "错误：这是目的表达，不能替代目标表达。"),
            ("のに", "错误：这是逆接表达，不能替代目标表达。"),
        ],
        f"正确：{expr} 是本题要确认的目标表达。",
    )


def natural_generic_options(
    point: str,
    meaning: str,
    category: str,
    example_jp: str = "",
    connection: str = "",
) -> list[tuple[str, bool, str]]:
    """Final fallback: every option must compete on the same grammar point."""

    def pack(correct: str, note: str, distractors: list[tuple[str, str]]) -> list[tuple[str, bool, str]]:
        return [(correct, True, note), *[(text, False, why) for text, why in distractors[:3]]]

    def example_target() -> str:
        match = re.search(r"（([^（）]{1,16})）", example_jp or "")
        if not match:
            return ""
        value = match.group(1).strip()
        return value if contains_japanese(value) else ""

    def looks_noisy(value: str) -> bool:
        clean = value.strip()
        if len(clean) > 34:
            return True
        if re.search(r"[0-9△。？！?]|ます|ました|です|でした|ています", clean):
            return True
        if any(mark in clean for mark in ["是", "的", "了", "・ ・", "一1", "立3"]):
            return True
        return False

    expr = primary_expression(point)
    ex_target = example_target()
    signal = f"{point} {meaning or ''} {category or ''} {connection or ''}"
    if ex_target and looks_noisy(expr):
        expr = ex_target

    priority_cases: list[tuple[tuple[str, ...], str, str, list[tuple[str, str]]]] = [
        (("くださいませんか",), "窓を開けてくださいませんか。", "正确：「てくださいませんか」是较礼貌的请求。",
         [("窓を開けたくださいませんか。", "错误：前面要接动词て形，不能接た形。"),
          ("窓を開けないでくださいませんか。", "错误：这是请求不要打开，语义不同。"),
          ("窓を開けるくださいませんか。", "错误：不能用辞书形直接接「くださいませんか」。")]),
        (("ようにしてください",), "明日は遅れないようにしてください。", "正确：「ようにしてください」用于委婉提醒或要求对方做到。",
         [("明日は遅れないでください。", "错误：意思接近但不是本题目标结构「ようにしてください」。"),
          ("明日は遅れるようにしてください。", "错误：语义变成请迟到，不合语境。"),
          ("明日は遅れたようにしてください。", "错误：接续和语义都不自然。")]),
        (("にかけて", "にかけては", "にかけても"), "料理の味にかけては、この店が一番だ。", "正确：「にかけては」表示在某方面评价特别突出。",
         [("料理の味をかけては、この店が一番だ。", "错误：应使用「にかけては」，不能用「を」。"),
          ("料理の味にかけては、駅へ行きます。", "错误：后项不是评价内容。"),
          ("料理の味にかけてはです。", "错误：后项缺少评价判断。")]),
    ]
    for keys, correct, note, distractors in priority_cases:
        if any(key in signal for key in keys):
            return pack(correct, note, distractors)

    pattern_cases: list[tuple[tuple[str, ...], str, str, list[tuple[str, str]]]] = [
        (("てください", "ないでください"), "ここに名前を書いてください。", "正确：「てください」用于请求对方做某事。",
         [("ここに名前を書いたください。", "错误：「ください」前要接动词て形，不能接た形。"),
          ("ここに名前を書くてください。", "错误：五段动词「書く」的て形是「書いて」。"),
          ("ここに名前を書かないでください。", "错误：这是“请不要写”，语义和请求写相反。")]),
        (("くださいませんか",), "窓を開けてくださいませんか。", "正确：「てくださいませんか」是较礼貌的请求。",
         [("窓を開けたくださいませんか。", "错误：前面要接动词て形，不能接た形。"),
          ("窓を開けないでくださいませんか。", "错误：这是请求不要打开，语义不同。"),
          ("窓を開けるくださいませんか。", "错误：不能用辞书形直接接「くださいませんか」。")]),
        (("させてください",), "少し休ませてください。", "正确：「させてください」表示请求允许自己做某事。",
         [("少し休んでください。", "错误：这是请求对方休息，不是请求允许自己休息。"),
          ("少し休ませます。", "错误：这是使役陈述，不是请求允许。"),
          ("少し休ませないでください。", "错误：语义变成请不要让休息，和目标相反。")]),
        (("ようにしてください",), "明日は遅れないようにしてください。", "正确：「ようにしてください」用于委婉提醒或要求对方做到。",
         [("明日は遅れないでください。", "错误：意思接近但不是本题目标结构「ようにしてください」。"),
          ("明日は遅れるようにしてください。", "错误：语义变成请迟到，不合语境。"),
          ("明日は遅れたようにしてください。", "错误：接续和语义都不自然。")]),
        (("なさい",), "早く宿題をしなさい。", "正确：「なさい」用于命令或指示。",
         [("早く宿題をするなさい。", "错误：「なさい」前接ます形词干，不能接辞书形。"),
          ("早く宿題をしてなさい。", "错误：「してなさい」语气和结构不同，不是目标命令形。"),
          ("早く宿題をしないなさい。", "错误：否定形不能这样接「なさい」。")]),
        (("甲斐",), "苦労したかいがあって、試験に合格した。", "正确：「かいがある」表示努力有价值、有成果。",
         [("苦労するかいがあって、試験に合格した。", "错误：这里通常说已付出的努力「苦労したかい」。"),
          ("苦労したかいで、試験に合格した。", "错误：固定搭配是「かいがあって」。"),
          ("苦労したかいがない、試験に合格した。", "错误：「かいがない」表示没有效果，和合格矛盾。")]),
        (("きっかけ", "契機"), "留学をきっかけに、日本語を勉強し始めた。", "正确：「をきっかけに」表示以某事为契机。",
         [("留学をきっかけで、日本語を勉強し始めた。", "错误：名词后常用「をきっかけに/として」，不是「をきっかけで」。"),
          ("留学がきっかけに、日本語を勉強し始めた。", "错误：「がきっかけで」可以，但「がきっかけに」不自然。"),
          ("日本語をきっかけに、留学を勉強し始めた。", "错误：契机和后项关系颠倒，语义不成立。")]),
        (("かけ",), "この本はまだ読みかけです。", "正确：「かけ」表示动作做到一半或即将发生。",
         [("この本はまだ読むかけです。", "错误：「かけ」前接动词ます形词干。"),
          ("この本は読みかけました。", "错误：「かけ」作名词性表达时这里应用「読みかけです」。"),
          ("この本は読み終わりかけです。", "错误：语义混乱，读完和做到一半冲突。")]),
        (("がたい",), "その話は信じがたい。", "正确：「がたい」表示心理上难以做到。",
         [("その話は信じにくいがたい。", "错误：「にくい」和「がたい」不能叠用。"),
          ("その話は信じるがたい。", "错误：「がたい」前接ます形词干。"),
          ("その話は信じがたいでする。", "错误：句尾结构错误。")]),
        (("がち",), "彼は約束を忘れがちだ。", "正确：「がち」表示容易出现某种倾向。",
         [("彼は約束を忘れるがちだ。", "错误：「がち」前接ます形词干。"),
          ("彼は約束を忘れにくいがちだ。", "错误：「にくい」和「がち」语义冲突。"),
          ("彼は約束を忘れがちをする。", "错误：「がち」后不能这样接「をする」。")]),
        (("か何か",), "お茶か何か飲みませんか。", "正确：「か何か」表示举出一个不确定的例子。",
         [("お茶を何か飲みませんか。", "错误：这里要用「名詞+か何か」。"),
          ("お茶か何かを飲みましたか何か。", "错误：「か何か」不能这样重复放在句尾。"),
          ("お茶か何かです飲みませんか。", "错误：接续不自然。")]),
        (("かねない",), "このままでは事故が起こりかねない。", "正确：「かねない」表示有可能发生不好的事情。",
         [("このままでは事故が起こるかねない。", "错误：「かねない」前接ます形词干。"),
          ("いいことが起こりかねない。", "错误：「かねない」多用于不好的可能性。"),
          ("事故が起こりかねる。", "错误：「かねる」表示难以做，和「かねない」不同。")]),
        (("かねる",), "そのご依頼はお引き受けしかねます。", "正确：「かねる」表示难以做、不能做的委婉说法。",
         [("そのご依頼はお引き受けするかねます。", "错误：「かねる」前接ます形词干。"),
          ("事故が起こりかねます。", "错误：表示可能发生坏事应使用「かねない」。"),
          ("喜んでお引き受けしかねます。", "错误：「喜んで」和「しかねます」语义矛盾。")]),
        (("かのよう",), "彼は何も知らないかのように話した。", "正确：「かのように」表示好像真的那样。",
         [("彼は何も知らないかのようだに話した。", "错误：修饰动词要用「かのように」。"),
          ("彼は何も知らないかのような話した。", "错误：「かのような」修饰名词，不直接修饰动词。"),
          ("彼は何も知らないかのように知っていた。", "错误：前后语义矛盾。")]),
        (("からこそ",), "努力したからこそ、合格できた。", "正确：「からこそ」强调正因为前项才有后项。",
         [("少し休んだからこそ、疲れた。", "错误：前后不是“正因为如此才”的强调关系。"),
          ("努力するからこそ、昨日合格できた。", "错误：时态关系不自然。"),
          ("努力したからこそです。", "错误：后项缺少结果内容。")]),
        (("からして",), "名前からして、外国人だと分かる。", "正确：「からして」表示单从某一点来看就能判断。",
         [("名前からして、駅へ行った。", "错误：后项不是判断内容。"),
          ("名前にして、外国人だと分かる。", "错误：应使用「からして」。"),
          ("外国人だと分かるからして、名前。", "错误：前后顺序和结构错误。")]),
        (("からすると", "からすれば", "から見る", "から見"), "専門家からすると、この方法は危険だ。", "正确：表示从某立场或角度来看。",
         [("専門家について、この方法は危険だ。", "错误：「について」表示话题，不表示判断立场。"),
          ("専門家に対して、この方法は危険だ。", "错误：「に対して」表示对象，不表示观点来源。"),
          ("この方法は危険だからすると、専門家。", "错误：结构顺序错误。")]),
        (("代わりに",), "兄の代わりに、私が会議に出た。", "正确：「代わりに」表示代替或交换。",
         [("兄のために、私が会議に出た。", "错误：「ために」表示目的或利益，不一定表示代替。"),
          ("兄の代わりで、私が会議に出た。", "错误：这里自然说「代わりに」。"),
          ("私が会議に出た代わりに兄。", "错误：后项结构不完整。")]),
        (("気味",), "今日は少し風邪気味だ。", "正确：「気味」表示有点某种倾向或状态。",
         [("今日は少し風邪の気味する。", "错误：接续和句尾都不自然。"),
          ("今日は風邪気味に寝た。", "错误：「気味に」不能这样修饰动作。"),
          ("今日は元気気味だ。", "错误：「気味」多用于不太好的倾向。")]),
        (("きれる", "きれない", "きる"), "宿題を全部やりきった。", "正确：「きる」表示完全做完。",
         [("宿題を全部やるきった。", "错误：「きる」前接ます形词干。"),
          ("宿題を全部やりがたい。", "错误：「がたい」表示心理上难以做到，不表示做完。"),
          ("宿題を全部やりきれない終わった。", "错误：「きれない」和完成语义矛盾。")]),
        (("くらい", "ぐらい"), "一時間ぐらい待ちました。", "正确：「ぐらい/くらい」表示大约的程度或数量。",
         [("一時間まで待ちました。", "错误：「まで」表示终点，不表示大约。"),
          ("一時間から待ちました。", "错误：「から」表示起点。"),
          ("一時間ぐらいを待ちました。", "错误：数量程度后不需要「を」。")]),
        (("末",), "悩んだ末に、留学することにした。", "正确：「末に」表示经过一段过程之后得出结果。",
         [("悩む末に、留学することにした。", "错误：「末に」前常接动词た形或名詞+の。"),
          ("悩んだ末で、留学することにした。", "错误：固定形式是「末に」。"),
          ("少し見た末に、すぐ決めた。", "错误：通常强调长时间或反复之后的结果。")]),
        (("ずにはいられない", "ないではいられない"), "その話を聞いて、笑わずにはいられなかった。", "正确：表示控制不住、不由得做某事。",
         [("その話を聞いて、笑うずにはいられなかった。", "错误：「ず」前接未然形，不接辞书形。"),
          ("その話を聞いて、笑わずに済んだ。", "错误：「ずに済む」表示不用做就解决，语义不同。"),
          ("その話を聞いて、笑わずにはいられないでする。", "错误：句尾结构错误。")]),
        (("だらけ",), "服が泥だらけになった。", "正确：「だらけ」表示满是某种不好的东西。",
         [("服が泥だけになった。", "错误：「だけ」表示仅仅，不表示满是。"),
          ("服が泥だらけをなった。", "错误：「だらけになる」中不能用「を」。"),
          ("服がきれいだらけになった。", "错误：「だらけ」多用于不好的东西。")]),
        (("ついでに",), "買い物のついでに、郵便局へ寄った。", "正确：「ついでに」表示顺便做后项。",
         [("買い物のために、郵便局へ寄った。", "错误：「ために」表示目的，不表示顺便。"),
          ("買い物をついでに、郵便局へ寄った。", "错误：名词接续常用「名詞+のついでに」。"),
          ("郵便局へ寄ったついでに、買い物の。", "错误：后项结构不完整。")]),
        (("っこない", "っこなし"), "そんな難しい問題はできっこない。", "正确：「っこない」表示绝不可能。",
         [("そんな問題はできるっこない。", "错误：「っこない」前接ます形词干。"),
          ("簡単だからできっこない。", "错误：前后语义矛盾。"),
          ("できっこないことができる。", "错误：表达自相矛盾。")]),
        (("つつある",), "景気は少しずつ回復しつつある。", "正确：「つつある」表示正在逐渐变化。",
         [("景気は回復するつつある。", "错误：「つつある」前接ます形词干。"),
          ("昨日景気は回復しつつある。", "错误：过去时间和现在逐渐变化不合。"),
          ("景気は回復しつつあるでした。", "错误：句尾结构错误。")]),
        (("っぽい",), "この服は子どもっぽい。", "正确：「っぽい」表示有某种倾向或感觉。",
         [("この服は子どものっぽい。", "错误：名词后直接接「っぽい」。"),
          ("この服は子どもっぽくです。", "错误：句尾结构错误。"),
          ("この服は大人っぽい子どもっぽい。", "错误：两个评价叠加后语义混乱。")]),
        (("つもりで",), "先生になったつもりで説明してみた。", "正确：「つもりで」表示抱着某种打算或假定心情。",
         [("先生になるつもりで昨日説明した。", "错误：这里不是将来打算，而是假定心情。"),
          ("先生になったために説明してみた。", "错误：「ために」表示原因或目的，不表示假定心情。"),
          ("先生になったつもりです説明した。", "错误：句中接续不自然。")]),
        (("つもり",), "来年、日本へ留学するつもりだ。", "正确：「つもりだ」表示打算。",
         [("去年、日本へ留学するつもりだ。", "错误：过去时间和现在打算不合。"),
          ("日本へ留学したつもりだが、実際に行った。", "错误：「つもり」表示自以为，和实际发生语义冲突。"),
          ("日本へ留学するためだつもり。", "错误：结构错误。")]),
        (("てでも",), "徹夜してでも、この仕事を終わらせる。", "正确：「てでも」表示即使采取极端手段也要做。",
         [("徹夜してでも、もう寝ます。", "错误：后项和“即使也要”的目的矛盾。"),
          ("徹夜するでも、この仕事を終わらせる。", "错误：「てでも」前接动词て形。"),
          ("徹夜してでもです。", "错误：后项缺少要达成的目标。")]),
        (("てはいられない",), "試験前だから、遊んではいられない。", "正确：「てはいられない」表示不能继续处于某状态。",
         [("試験前だから、遊んではいる。", "错误：没有表达“不能继续”。"),
          ("昨日遊んではいられない。", "错误：过去事实语境不自然。"),
          ("遊んではいられないでする。", "错误：句尾结构错误。")]),
        (("というより",), "彼は優しいというより、気が弱い。", "正确：「というより」表示与其说前项不如说后项。",
         [("彼は優しいというよりです。", "错误：后项缺少重新判断的内容。"),
          ("彼は優しいから、気が弱い。", "错误：这是原因，不是重新评价。"),
          ("気が弱いというより、彼は優しいというより。", "错误：结构重复且不完整。")]),
        (("とおり", "どおり"), "先生が言ったとおりに書いてください。", "正确：「とおりに」表示按照前项那样做。",
         [("先生が言ったために書いてください。", "错误：「ために」表示目的或原因，不表示按照。"),
          ("先生が言ったとおりを書いてください。", "错误：修饰动作时自然用「とおりに」。"),
          ("先生が言うとおりに昨日書いたください。", "错误：时态和句尾不自然。")]),
        (("とか",), "週末は映画を見るとか買い物するとかして過ごします。", "正确：「とか」用于列举例子。",
         [("週末は映画を見るために買い物するとか。", "错误：目的关系和列举混在一起。"),
          ("映画を見るとかです。", "错误：列举内容不完整。"),
          ("映画を見たとか買い物したから過ごします。", "错误：原因连接不自然。")]),
        (("どころか",), "漢字どころか、ひらがなも読めない。", "正确：「どころか」表示别说前项，连后项也不成立或更进一步。",
         [("漢字どころか、漢字が読める。", "错误：前后没有递进反差。"),
          ("漢字のために、ひらがなも読めない。", "错误：这是原因目的关系，不是递进否定。"),
          ("漢字どころかです。", "错误：后项缺少对比内容。")]),
        (("ところだった",), "もう少しで電車に遅れるところだった。", "正确：「ところだった」表示差点发生某事。",
         [("昨日電車に遅れたところだった。", "错误：已发生事实不表示差点。"),
          ("電車に遅れるためだった。", "错误：这是目的/原因形式，不表示差点。"),
          ("電車に遅れるところですだった。", "错误：句尾结构错误。")]),
        (("どころではない",), "忙しくて、旅行どころではない。", "正确：「どころではない」表示不是做某事的时候。",
         [("暇なので、旅行どころではない。", "错误：前后语义矛盾。"),
          ("旅行どころです。", "错误：缺少否定结构。"),
          ("旅行のためではない。", "错误：不是目标表达。")]),
        (("としか言いようがない",), "この結果は残念としか言いようがない。", "正确：表示只能这样评价。",
         [("この結果は残念だけ言いようがない。", "错误：固定表达是「としか言いようがない」。"),
          ("この結果は残念としか言いようがある。", "错误：「しか」要与否定呼应。"),
          ("残念と言うためがない。", "错误：结构错误。")]),
        (("とともに",), "年を取るとともに、体力が落ちる。", "正确：「とともに」表示随着前项变化后项也变化。",
         [("年を取るために、体力が落ちる。", "错误：「ために」表示目的或原因，不表示同步变化。"),
          ("年を取るとともにです。", "错误：后项缺少变化内容。"),
          ("体力が落ちるとともに、年を取る。", "错误：因果和时间变化关系不自然。")]),
        (("とは限らない",), "高いものが必ずいいとは限らない。", "正确：「とは限らない」表示不一定。",
         [("高いものが必ずいいとは限る。", "错误：目标表达是否定「限らない」。"),
          ("高いものが必ずいいに限らない。", "错误：接续错误。"),
          ("高いものが必ずいいとは限らないでする。", "错误：句尾结构错误。")]),
        (("に限って", "に限り"), "大事な日に限って、雨が降る。", "正确：「に限って」表示偏偏在某种情况发生。",
         [("大事な日について、雨が降る。", "错误：「について」表示话题，不表示偏偏。"),
          ("大事な日に限ってです。", "错误：后项缺少发生的事情。"),
          ("雨が降るに限って、大事な日。", "错误：结构顺序错误。")]),
        (("はもちろん", "はもとより"), "漢字はもちろん、会話も得意だ。", "正确：表示前项不用说，后项也如此。",
         [("漢字はもちろんです。", "错误：缺少追加说明的后项。"),
          ("漢字のために、会話も得意だ。", "错误：这是原因或目的，不是追加强调。"),
          ("会話も得意だはもちろん、漢字。", "错误：结构顺序错误。")]),
        (("まま",), "窓を開けたまま寝てしまった。", "正确：「まま」表示保持前项状态。",
         [("窓を開けるまま寝てしまった。", "错误：这里表示状态保持，常用た形。"),
          ("窓を開けたため寝てしまった。", "错误：「ため」表示原因，不表示状态保持。"),
          ("窓を開けたままです寝た。", "错误：句中结构错误。")]),
        (("もかまわず",), "雨にもかまわず、彼は出かけた。", "正确：「もかまわず」表示不顾前项。",
         [("雨にもかまって、彼は出かけた。", "错误：不是目标表达。"),
          ("雨にもかまわずです。", "错误：后项缺少动作。"),
          ("彼は出かけたにもかまわず雨。", "错误：结构顺序错误。")]),
        (("を通じて", "を通して"), "一年を通じて、この町は暖かい。", "正确：「を通じて」表示整个期间或通过某媒介。",
         [("一年について、この町は暖かい。", "错误：「について」表示话题。"),
          ("一年を通じてです。", "错误：后项缺少说明。"),
          ("この町は暖かいを通じて一年。", "错误：结构顺序错误。")]),
        (("わけにはいかない",), "約束があるので、帰るわけにはいかない。", "正确：表示由于道理或情况不能做某事。",
         [("約束があるので、帰ることができる。", "错误：这是能做，不是不能做。"),
          ("帰るわけではない。", "错误：「わけではない」表示并非，不是不能。"),
          ("帰るわけにはいかないでする。", "错误：句尾结构错误。")]),
        (("かもしれない",), "明日は雨が降るかもしれない。", "正确：「かもしれない」表示可能性。",
         [("明日は雨が降るに違いない。", "错误：「に違いない」表示很有把握，语气太强。"),
          ("明日は雨が降るはずがない。", "错误：「はずがない」表示不可能，语义相反。"),
          ("明日は雨が降るかもしれないでする。", "错误：句尾结构错误。")]),
        (("ことができる",), "私は日本語を話すことができる。", "正确：「ことができる」表示能力或可能。",
         [("私は日本語を話したことができる。", "错误：「ことができる」前接动词辞书形。"),
          ("私は日本語を話すことがある。", "错误：「ことがある」表示经验，不表示能力。"),
          ("私は日本語を話すことにする。", "错误：「ことにする」表示决定，不表示能力。")]),
        (("しかない",), "時間がないので、急ぐしかない。", "正确：「しかない」表示除此之外别无选择。",
         [("時間がないので、急ぐだけではない。", "错误：「だけではない」表示不只是，不是别无选择。"),
          ("時間がないので、急ぐことがある。", "错误：「ことがある」表示有时或经验。"),
          ("時間がないので、急ぐしかある。", "错误：「しか」要和否定呼应。")]),
        (("しか",), "財布には千円しかありません。", "正确：「しか」与否定呼应，表示只有。",
         [("財布には千円だけありません。", "错误：「だけ」不与否定这样搭配表示只有。"),
          ("財布には千円しかあります。", "错误：「しか」要与否定呼应。"),
          ("財布には千円もありません。", "错误：「もありません」表示连一千日元也没有，语义不同。")]),
        (("ずとも",), "詳しく説明せずとも、意味は分かる。", "正确：「ずとも」表示即使不做前项也成立。",
         [("詳しく説明するずとも、意味は分かる。", "错误：「ず」前接未然形，不接辞书形。"),
          ("詳しく説明せずに済む、意味は分かる。", "错误：「ずに済む」表示不用做就解决，语义不同。"),
          ("意味は分かるずとも、説明します。", "错误：前后关系不自然。")]),
        (("ず(に)", "ずに", "ないで"), "朝ご飯を食べずに出かけた。", "正确：「ずに/ないで」表示不做前项就做后项。",
         [("朝ご飯を食べるずに出かけた。", "错误：「ずに」前接未然形。"),
          ("朝ご飯を食べてから出かけた。", "错误：「てから」表示做完前项后再做后项，语义相反。"),
          ("朝ご飯を食べずにです。", "错误：后项动作不完整。")]),
        (("せる/させる", "使役"), "母は子どもに部屋を掃除させた。", "正确：使役形表示让某人做某事。",
         [("母は子どもを部屋に掃除させた。", "错误：动作主体和地点助词混乱。"),
          ("母は子どもに部屋を掃除された。", "错误：这是被动，不是使役。"),
          ("母は子どもに部屋を掃除するさせた。", "错误：不能用辞书形直接接「させた」。")]),
        (("そうにない", "そうもない", "そうではない"), "この雨はすぐにはやみそうにない。", "正确：「そうにない」表示看起来不会发生。",
         [("この雨はすぐにはやむそうにない。", "错误：「そうにない」前接ます形词干。"),
          ("この雨はすぐにはやみそうだ。", "错误：「そうだ」表示看起来会发生，语义相反。"),
          ("この雨はすぐにはやみそうにないでする。", "错误：句尾结构错误。")]),
        (("たいものだ",), "一度、富士山に登ってみたいものだ。", "正确：「たいものだ」表示强烈愿望或感慨。",
         [("一度、富士山に登ったものだ。", "错误：「たものだ」表示回忆过去习惯。"),
          ("一度、富士山に登りたいことだ。", "错误：不是自然表达。"),
          ("富士山に登ってみたいものだです。", "错误：句尾结构错误。")]),
        (("だけでなく",), "彼は英語だけでなく、中国語も話せる。", "正确：「だけでなく」表示不但...而且。",
         [("彼は英語だけでは、中国語も話せる。", "错误：「だけでは」表示只靠前项的话，不表示追加。"),
          ("彼は英語だけでなくです。", "错误：缺少追加内容。"),
          ("中国語も話せるだけでなく、彼は英語。", "错误：结构顺序不自然。")]),
        (("だけでは",), "努力だけでは、成功できない。", "正确：「だけでは」表示只靠前项不足以成立。",
         [("努力だけでなく、成功できない。", "错误：「だけでなく」表示追加，不表示不足。"),
          ("努力だけではです。", "错误：后项判断不完整。"),
          ("成功できないだけでは努力。", "错误：结构顺序错误。")]),
        (("たとえ", "たとい"), "たとえ雨でも、試合は行われる。", "正确：「たとえ～ても」表示即使。",
         [("たとえ雨だから、試合は行われる。", "错误：「たとえ」要与「ても/でも」呼应。"),
          ("雨でも、たとえ試合は行われる。", "错误：「たとえ」位置不自然。"),
          ("たとえ雨でもです。", "错误：后项缺少成立内容。")]),
        (("たまえ",), "静かに聞きたまえ。", "正确：「たまえ」用于上对下的命令或指示。",
         [("静かに聞くたまえ。", "错误：「たまえ」前接ます形词干。"),
          ("静かに聞いてたまえ。", "错误：不是目标命令形式。"),
          ("静かに聞かないたまえ。", "错误：否定接续错误。")]),
        (("ちゃう", "じゃう"), "宿題を忘れちゃった。", "正确：「ちゃう」是「てしまう」的口语形式。",
         [("宿題を忘れるちゃった。", "错误：「ちゃう」前接て形变化。"),
          ("宿題を忘れちゃうでした。", "错误：句尾结构错误。"),
          ("宿題を忘れないちゃった。", "错误：否定接续不自然。")]),
        (("てあげる", "てさしあげる", "てやる"), "友だちに日本語を教えてあげた。", "正确：「てあげる」表示为别人做某事。",
         [("友だちが日本語を教えてあげた。", "错误：主语变成朋友，授受方向不清。"),
          ("友だちに日本語を教えてくれた。", "错误：「てくれる」表示别人为我方做。"),
          ("友だちに日本語を教えるあげた。", "错误：前接动词て形。")]),
        (("てくれる", "てくださる"), "友だちが手伝ってくれた。", "正确：「てくれる」表示别人为我方做某事。",
         [("私は友だちを手伝ってくれた。", "错误：主语是自己时授受方向不对。"),
          ("友だちに手伝ってあげた。", "错误：「てあげる」表示我为别人做。"),
          ("友だちが手伝うくれた。", "错误：前接动词て形。")]),
        (("ていく",), "これからも日本語を勉強していく。", "正确：「ていく」表示动作或变化向将来持续。",
         [("昨日から日本語を勉強していく。", "错误：过去起点强调到现在时更自然用「てきた」。"),
          ("日本語を勉強しておく。", "错误：「ておく」表示预先准备。"),
          ("日本語を勉強してしまう。", "错误：「てしまう」强调完成或遗憾。")]),
        (("てくる",), "最近、だんだん寒くなってきた。", "正确：「てくる」表示变化从过去发展到现在。",
         [("これから寒くなってきた。", "错误：将来方向应更自然用「ていく」。"),
          ("寒くなっておく。", "错误：「ておく」表示预先准备。"),
          ("寒くなってしまう。", "错误：「てしまう」表示完成或遗憾。")]),
        (("て済む", "で済む"), "メールで連絡して済んだ。", "正确：「て済む」表示用某种做法就解决。",
         [("メールで連絡して困った。", "错误：不是“解决”的语义。"),
          ("メールで連絡する済んだ。", "错误：「済む」前接て形。"),
          ("メールで連絡して済むためだ。", "错误：结构不自然。")]),
        (("てちょうだい",), "少し待ってちょうだい。", "正确：「てちょうだい」是较口语的请求。",
         [("少し待つちょうだい。", "错误：前接动词て形。"),
          ("少し待ったちょうだい。", "错误：不能接た形。"),
          ("少し待たないでちょうだい。", "错误：这是请求不要等，语义相反。")]),
        (("てほしい",), "もう少し静かにしてほしい。", "正确：「てほしい」表示希望别人做某事。",
         [("私は静かにしてほしい。", "错误：若主语是自己，通常不是希望别人做。"),
          ("静かにするほしい。", "错误：前接动词て形。"),
          ("静かにしてほしいでする。", "错误：句尾结构错误。")]),
        (("てみせる",), "今度こそ、必ず合格してみせる。", "正确：「てみせる」表示一定要做给别人看。",
         [("合格してみる。", "错误：「てみる」表示试着做，语气不同。"),
          ("合格するみせる。", "错误：前接动词て形。"),
          ("合格してみせるかもしれない。", "错误：决心语气被可能性削弱。")]),
        (("てみる",), "新しい方法を試してみる。", "正确：「てみる」表示试着做。",
         [("新しい方法を試すみる。", "错误：前接动词て形。"),
          ("新しい方法を試しておく。", "错误：「ておく」表示预先准备。"),
          ("新しい方法を試してしまう。", "错误：「てしまう」表示完成或遗憾。")]),
        (("というものは",), "仕事というものは大変だ。", "正确：「というものは」用于说明某类事物的一般性质。",
         [("仕事というものは昨日した。", "错误：后项不是一般性质说明。"),
          ("仕事というものが大変だ。", "错误：不是目标表达。"),
          ("仕事というものはです。", "错误：后项判断不完整。")]),
        (("ながらも",), "知っていながらも、彼は何も言わなかった。", "正确：「ながらも」表示逆接。",
         [("音楽を聞きながらも、勉強した。", "错误：这里更自然是同时动作「ながら」。"),
          ("知っていながらもです。", "错误：后项缺少逆接内容。"),
          ("彼は何も言わなかったながらも、知っていた。", "错误：前后顺序不自然。")]),
        (("ながら",), "音楽を聞きながら、勉強します。", "正确：「ながら」表示两个动作同时进行。",
         [("音楽を聞くながら、勉強します。", "错误：「ながら」前接ます形词干。"),
          ("音楽を聞きながらです。", "错误：后项动作不完整。"),
          ("勉強しながら、昨日音楽を聞いた。", "错误：时态和同时关系不自然。")]),
        (("ないで済む", "ずに済む"), "薬を飲まないで済んだ。", "正确：「ないで済む」表示不用做某事也解决了。",
         [("薬を飲まないではいられなかった。", "错误：「ないではいられない」表示忍不住要做，语义不同。"),
          ("薬を飲まないで困った。", "错误：不是“解决”的语义。"),
          ("薬を飲むないで済んだ。", "错误：接续错误。")]),
        (("ねばならない", "ねばならぬ"), "明日までにこの仕事を終えねばならない。", "正确：「ねばならない」表示必须。",
         [("この仕事を終えるねばならない。", "错误：「ねば」接未然形。"),
          ("この仕事を終えなくてもいい。", "错误：表示不必，语义相反。"),
          ("この仕事を終えねばならないかもしれない。", "错误：可能性削弱了必须的语气。")]),
        (("はず",), "彼はもうすぐ来るはずだ。", "正确：「はずだ」表示按理应该。",
         [("彼はもうすぐ来るわけではない。", "错误：「わけではない」表示并非，不是推断。"),
          ("彼はもうすぐ来るためだ。", "错误：「ためだ」表示原因或目的，不是推断。"),
          ("彼はもうすぐ来るはずでする。", "错误：句尾结构错误。")]),
        (("ほど",), "涙が出るほど嬉しかった。", "正确：「ほど」表示程度。",
         [("涙が出るまで嬉しかった。", "错误：「まで」表示终点，程度表达不自然。"),
          ("涙が出るから嬉しかった。", "错误：这是原因连接，语义不自然。"),
          ("涙が出るほどです嬉しかった。", "错误：结构错误。")]),
        (("べき",), "約束は守るべきだ。", "正确：「べきだ」表示应该。",
         [("約束は守らなくてもいい。", "错误：表示不必，语义相反。"),
          ("約束は守るはずだ。", "错误：「はずだ」表示推断，不是应该。"),
          ("約束は守るべきでする。", "错误：句尾结构错误。")]),
        (("までに",), "五時までに来てください。", "正确：「までに」表示期限之前。",
         [("五時まで来てください。", "错误：「まで」表示持续到五点，不表示截止点。"),
          ("五時から来てください。", "错误：「から」表示起点。"),
          ("五時までにいます。", "错误：这里不是到达期限的表达。")]),
        (("みたい",), "彼は子どもみたいだ。", "正确：「みたいだ」表示比喻或样态。",
         [("彼は子どものみたいだ。", "错误：名词后直接接「みたいだ」。"),
          ("彼は子どもためだ。", "错误：「ため」表示原因或目的，不表示比喻。"),
          ("彼は子どもみたいでする。", "错误：句尾结构错误。")]),
        (("やすい",), "このペンは書きやすい。", "正确：「やすい」表示容易做某事。",
         [("このペンは書くやすい。", "错误：「やすい」前接ます形词干。"),
          ("このペンは書きにくい。", "错误：「にくい」表示难做，语义相反。"),
          ("このペンは書きやすいでする。", "错误：句尾结构错误。")]),
        (("向け",), "これは子ども向けの本です。", "正确：「向け」表示面向某对象。",
         [("これは子ども向きの本です。", "错误：「向き」表示适合，和面向对象不同。"),
          ("これは子どもに対しての本です。", "错误：「に対して」不自然地表示受众。"),
          ("これは子ども向けです本。", "错误：语序错误。")]),
        (("向き",), "この靴は登山向きです。", "正确：「向き」表示适合某用途或对象。",
         [("この靴は登山向けです。", "错误：「向け」偏向面向对象，不是适合性质。"),
          ("この靴は登山についてです。", "错误：「について」表示话题。"),
          ("この靴は登山向きする。", "错误：句尾结构错误。")]),
        (("おきに",), "一日おきに薬を飲んでください。", "正确：「おきに」表示每隔一定间隔。",
         [("一日ごとに薬を飲んでください。", "错误：「ごとに」也可表示每次，但不是本题目标表达。"),
          ("一日までに薬を飲んでください。", "错误：「までに」表示期限。"),
          ("一日おきにです。", "错误：后项动作不完整。")]),
        (("がする",), "隣の部屋から変な音がする。", "正确：「がする」表示感觉到声音、气味或味道等。",
         [("隣の部屋から変な音をする。", "错误：「音がする」固定用「が」。"),
          ("隣の部屋から変な音にする。", "错误：「にする」表示决定或使成为。"),
          ("隣の部屋から変な音がある。", "错误：这里自然说「音がする」。")]),
        (("ことがある", "こともある"), "京都へ行ったことがある。", "正确：「ことがある」表示曾经有过某种经历。",
         [("京都へ行くことがある。", "错误：表示经历时前接た形。"),
          ("京都へ行ったことにする。", "错误：「ことにする」表示决定。"),
          ("京都へ行ったばかりがある。", "错误：结构错误。")]),
        (("たち", "がた"), "学生たちは教室にいます。", "正确：「たち」接在人或动物后表示复数。",
         [("学生をちは教室にいます。", "错误：「たち」不能替代助词。"),
          ("学生たちを教室にいます。", "错误：这里要用主题或主语，不是动作对象。"),
          ("学生がたちは教室にいます。", "错误：「がた」と「たち」不能这样叠用。")]),
        (("ませんか",), "一緒に映画を見ませんか。", "正确：「ませんか」用于邀请或询问对方意愿。",
         [("一緒に映画を見ませんでしたか。", "错误：这是询问过去事实，不是邀请。"),
          ("一緒に映画を見ないでください。", "错误：这是请求不要做。"),
          ("一緒に映画を見ませんかです。", "错误：句尾结构错误。")]),
        (("ましょう", "ましよう"), "一緒に昼ご飯を食べましょう。", "正确：「ましょう」用于劝诱或一起做某事。",
         [("一緒に昼ご飯を食べました。", "错误：这是过去陈述，不是劝诱。"),
          ("一緒に昼ご飯を食べませんでした。", "错误：这是否定过去，不是劝诱。"),
          ("一緒に昼ご飯を食べましょうです。", "错误：句尾结构错误。")]),
        (("にする", "くする"), "会議は明日にする。", "正确：「にする」表示决定或选择。",
         [("会議は明日になる。", "错误：「になる」表示自然变化或结果，不是主动决定。"),
          ("会議は明日をする。", "错误：助词和结构错误。"),
          ("会議は明日にするです。", "错误：句尾结构错误。")]),
        (("ということ",), "彼が来ないということは、何かあったのだろう。", "正确：「ということ」把前面的内容作为一件事来说明。",
         [("彼が来ないというものは、何かあったのだろう。", "错误：「というものは」说明一般性质，不适合这里。"),
          ("彼が来ないということでする。", "错误：句尾结构错误。"),
          ("何かあったということは、彼が来ないだろう。", "错误：前后推理关系不自然。")]),
        (("という",), "田中という人から電話がありました。", "正确：「という」用于名称、引用或说明。",
         [("田中について人から電話がありました。", "错误：「について」表示话题，不表示叫作。"),
          ("田中というから電話がありました。", "错误：后面缺少被说明的名词。"),
          ("田中という人です電話がありました。", "错误：句中结构错误。")]),
        (("そうだ",), "天気予報によると、明日は雨が降るそうだ。", "正确：「そうだ」可表示传闻。",
         [("空が暗いので、雨が降るそうだ。", "错误：看样态时应用「降りそうだ」。"),
          ("明日は雨が降ったそうだ。", "错误：若说明明天的传闻，不能用过去形。"),
          ("明日は雨が降るそうでする。", "错误：句尾结构错误。")]),
        (("らしい",), "彼は学生らしい。", "正确：「らしい」表示推量或具有典型性质。",
         [("彼は学生みたいに学生だ。", "错误：结构重复，不是目标表达。"),
          ("彼は学生ためだ。", "错误：「ため」表示原因或目的。"),
          ("彼は学生らしいでする。", "错误：句尾结构错误。")]),
        (("てもかまわない",), "少し遅れてもかまいません。", "正确：「てもかまわない」表示即使那样也没关系。",
         [("少し遅れてはいけません。", "错误：「てはいけない」表示禁止。"),
          ("少し遅れなければなりません。", "错误：表示必须迟到，语义不合。"),
          ("少し遅れてもかまいませんです。", "错误：句尾结构错误。")]),
        (("てはいけない",), "ここで写真を撮ってはいけません。", "正确：「てはいけない」表示禁止。",
         [("ここで写真を撮ってもかまいません。", "错误：表示许可，语义相反。"),
          ("ここで写真を撮らなければなりません。", "错误：表示必须拍照，语义相反。"),
          ("ここで写真を撮ってはいけませんです。", "错误：句尾结构错误。")]),
        (("なくては", "なければならない", "なくてはいけない"), "明日までに宿題を出さなければならない。", "正确：表示必须做某事。",
         [("明日までに宿題を出さなくてもいい。", "错误：表示不必，语义相反。"),
          ("明日までに宿題を出してはいけない。", "错误：表示禁止，语义相反。"),
          ("宿題を出すなければならない。", "错误：接续错误。")]),
        (("だす",), "雨が急に降りだした。", "正确：「だす」表示动作或状态开始。",
         [("雨が急に降るだした。", "错误：「だす」前接ます形词干。"),
          ("雨が急に降りつづけた。", "错误：「つづける」表示持续，不表示开始。"),
          ("雨が急に降りだす終わった。", "错误：开始和结束混在一起。")]),
        (("つづける", "続ける"), "彼は三時間走りつづけた。", "正确：「つづける」表示动作持续。",
         [("彼は三時間走るつづけた。", "错误：前接ます形词干。"),
          ("彼は三時間走りだした。", "错误：「だす」表示开始，不表示持续。"),
          ("彼は三時間走りつづけ終わった。", "错误：结构不自然。")]),
        (("方",), "この漢字の読み方を教えてください。", "正确：「方」接ます形词干，表示做法。",
         [("この漢字の読む方を教えてください。", "错误：「方」前接ます形词干。"),
          ("この漢字の読みためを教えてください。", "错误：「ため」表示目的或原因。"),
          ("この漢字の読み方です教えてください。", "错误：句中结构错误。")]),
        (("ところ",), "今、宿題をしているところです。", "正确：「ところ」表示动作阶段或时间点。",
         [("今、宿題をするところでした昨日。", "错误：时间和句尾不自然。"),
          ("宿題をしているためです。", "错误：「ため」表示原因或目的。"),
          ("今、宿題をしていることです。", "错误：「こと」不能自然替代动作阶段。")]),
        (("たり",), "週末は映画を見たり、買い物をしたりします。", "正确：「たり」用于列举动作例子。",
         [("週末は映画を見るたり、買い物をするたりします。", "错误：「たり」前接た形。"),
          ("週末は映画を見たりです。", "错误：列举内容不完整。"),
          ("映画を見たりから、買い物をします。", "错误：不能用「たりから」连接原因。")]),
        (("だけ",), "今日は水だけ飲みました。", "正确：「だけ」表示限定，仅仅。",
         [("今日は水しか飲みました。", "错误：「しか」要与否定呼应。"),
          ("今日は水まで飲みました。", "错误：「まで」表示甚至或终点，语义不同。"),
          ("今日は水だけをです。", "错误：句尾结构错误。")]),
        (("ようと思う", "うと思う"), "来年、日本へ留学しようと思う。", "正确：「ようと思う」表示意志或打算。",
         [("来年、日本へ留学すると思う。", "错误：这是推量“我想会...”，不是意志。"),
          ("去年、日本へ留学しようと思う。", "错误：过去时间和现在打算不合。"),
          ("日本へ留学しようと思うです。", "错误：句尾结构错误。")]),
        (("ていただく",), "先生に作文を見ていただいた。", "正确：「ていただく」表示请上位者为自己做某事。",
         [("先生に作文を見てあげた。", "错误：「てあげる」表示自己为别人做，方向相反。"),
          ("先生が作文を見てくれましたいただいた。", "错误：授受表达混乱。"),
          ("先生に作文を見るいただいた。", "错误：前接动词て形。")]),
        (("ございます",), "こちらが会議室でございます。", "正确：「ございます」是「あります/です」的礼貌表达。",
         [("こちらが会議室をございます。", "错误：助词错误。"),
          ("こちらが会議室でありますございます。", "错误：敬语形式重复。"),
          ("こちらが会議室でございますです。", "错误：句尾重复。")]),
        (("おっしゃる", "おっしやる"), "先生がおっしゃったことを覚えています。", "正确：「おっしゃる」是「言う」的尊敬语。",
         [("先生が申したことを覚えています。", "错误：「申す」是谦让语，不用于尊敬对方。"),
          ("先生がおっしゃるしました。", "错误：活用错误。"),
          ("私がおっしゃったことを覚えています。", "错误：通常不用尊敬语抬高自己。")]),
        (("いらっしゃる", "いらっ"), "先生は会議室にいらっしゃいます。", "正确：「いらっしゃる」是「いる/行く/来る」的尊敬语。",
         [("私は会議室にいらっしゃいます。", "错误：通常不用尊敬语抬高自己。"),
          ("先生は会議室におります。", "错误：「おる」是谦让语/郑重语，不用于尊敬先生。"),
          ("先生は会議室にいらっしゃるします。", "错误：活用错误。")]),
        (("拝見",), "資料を拝見しました。", "正确：「拝見する」是「見る」的谦让语。",
         [("先生が資料を拝見しました。", "错误：不能用谦让语降低先生的动作。"),
          ("資料を見られました拝見しました。", "错误：敬语形式混乱。"),
          ("資料を拝見するしました。", "错误：活用错误。")]),
        (("申し上げる",), "心からお礼を申し上げます。", "正确：「申し上げる」是「言う」的谦让语。",
         [("先生がお礼を申し上げます。", "错误：不应用谦让语降低先生的动作。"),
          ("お礼をおっしゃります。", "错误：「おっしゃる」是尊敬语，方向不同。"),
          ("お礼を申し上げるします。", "错误：活用错误。")]),
        (("申す",), "私は田中と申します。", "正确：「申す」是「言う」的谦让语。",
         [("先生は田中と申します。", "错误：介绍尊敬对象时不宜用谦让语。"),
          ("私は田中とおっしゃいます。", "错误：「おっしゃる」是尊敬语，不能用于自己。"),
          ("私は田中と申すです。", "错误：句尾结构错误。")]),
        (("参る",), "ただ今、そちらへ参ります。", "正确：「参る」是「行く/来る」的谦让语。",
         [("先生がこちらへ参ります。", "错误：不应用谦让语降低先生的动作。"),
          ("私はそちらへいらっしゃいます。", "错误：「いらっしゃる」是尊敬语，不能用于自己。"),
          ("そちらへ参るします。", "错误：活用错误。")]),
        (("いたす",), "後ほどこちらから連絡いたします。", "正确：「いたす」是「する」的谦让语。",
         [("先生が連絡いたします。", "错误：不应用谦让语降低先生的动作。"),
          ("私が連絡なさいます。", "错误：「なさる」是尊敬语，不能用于自己。"),
          ("連絡するいたします。", "错误：不能这样重复接续。")]),
        (("おる",), "私は受付で待っております。", "正确：「おる」是「いる」的谦让语或郑重语。",
         [("先生は受付で待っております。", "错误：对先生通常用尊敬语「いらっしゃいます」。"),
          ("私は受付で待っていらっしゃいます。", "错误：尊敬语不能用于自己。"),
          ("待っておるです。", "错误：句尾结构错误。")]),
    ]
    for keys, correct, note, distractors in pattern_cases:
        if any(key in signal for key in keys):
            return pack(correct, note, distractors)

    if "形容詞の" in signal or ("形容詞" in signal and "代替" in signal):
        return pack(
            "赤い（の）をください。",
            "正确：「の」代替前面提到的名词，相当于“红色的那个”。",
            [
                ("赤い（こと）をください。", "错误：「こと」表示抽象事情，不能指代具体物品。"),
                ("赤い（な）をください。", "错误：「な」不能这样接在い形容词后面代替名词。"),
                ("赤い（ため）をください。", "错误：「ため」表示目的或原因，不能代替名词。"),
            ],
        )

    if "な形容詞" in signal:
        return pack(
            "「静か」は（な形容詞）です。",
            "正确：「静か」は修饰名词时接「な」，属于な形容词。",
            [
                ("「おいしい」は（な形容詞）です。", "错误：「おいしい」是い形容词。"),
                ("「行く」は（な形容詞）です。", "错误：「行く」是动词。"),
                ("「学生」は（な形容詞）です。", "错误：「学生」是名词。"),
            ],
        )

    if "い形容詞" in signal or "し形容詞" in signal or ("形容詞" in signal and "な形容詞" not in signal):
        return pack(
            "「おいしい」は（い形容詞）です。",
            "正确：「おいしい」以「い」结尾，可作为い形容词使用。",
            [
                ("「静か」は（い形容詞）です。", "错误：「静か」是な形容词，修饰名词时是「静かな」。"),
                ("「行く」は（い形容詞）です。", "错误：「行く」是动词。"),
                ("「学生」は（い形容詞）です。", "错误：「学生」是名词。"),
            ],
        )

    particle_options = {
        "さん": ("田中（さん）は日本語の先生です。", "正确：「さん」接在人名后表示礼貌称呼。",
                 [("田中（を）は日本語の先生です。", "错误：「を」标记动作对象，不能用于称呼。"),
                  ("田中（で）は日本語の先生です。", "错误：「で」表示场所或手段，不能用于称呼。"),
                  ("田中（から）は日本語の先生です。", "错误：「から」表示起点或原因，不能用于称呼。")]),
        "を": ("朝ご飯（を）食べました。", "正确：「を」标记动作对象。",
              [("朝ご飯（に）食べました。", "错误：「に」不能标记「食べる」的直接对象。"),
               ("朝ご飯（で）食べました。", "错误：「で」表示场所或手段。"),
               ("朝ご飯（が）食べました。", "错误：「が」会把朝饭当主语。")]),
        "に": ("明日、学校（に）行きます。", "正确：「に」标记移动的到达点。",
              [("明日、学校（を）行きます。", "错误：「を」不能标记普通移动动词的到达点。"),
               ("明日、学校（で）行きます。", "错误：「で」表示动作场所，不表示到达点。"),
               ("明日、学校（から）行きます。", "错误：「から」表示出发点。")]),
        "で": ("図書館（で）勉強します。", "正确：「で」标记动作发生的场所。",
              [("図書館（に）勉強します。", "错误：「に」不自然，不能标记学习发生的场所。"),
               ("図書館（を）勉強します。", "错误：「を」标记动作对象。"),
               ("図書館（から）勉強します。", "错误：「から」表示起点。")]),
        "は": ("私（は）学生です。", "正确：「は」提示主题。",
              [("私（を）学生です。", "错误：「を」不能提示判断句主题。"),
               ("私（で）学生です。", "错误：「で」不用于提示主题。"),
               ("私（から）学生です。", "错误：「から」表示起点或原因。")]),
        "が": ("値段は高い（が）、品質はいい。", "正确：「が」可连接前后相反或铺垫内容。",
              [("値段は高い（ので）、品質はいい。", "错误：「ので」表示原因，不能表达转折。"),
               ("値段は高い（なら）、品質はいい。", "错误：「なら」表示条件，不表示转折。"),
               ("値段は高い（ために）、品質はいい。", "错误：「ために」表示目的或原因，不表示逆接。")]),
        "から": ("東京（から）来ました。", "正确：「から」表示出发点或起点。",
                [("東京（まで）来ました。", "错误：「まで」表示终点。"),
                 ("東京（を）来ました。", "错误：「を」不能标记来处。"),
                 ("東京（で）来ました。", "错误：「で」表示场所或手段。")]),
        "まで": ("五時（まで）待ちます。", "正确：「まで」表示时间或范围终点。",
                [("五時（から）待ちます。", "错误：「から」表示起点。"),
                 ("五時（で）待ちます。", "错误：「で」不能表示等待终点。"),
                 ("五時（を）待ちます。", "错误：「を」会把时间当动作对象。")]),
        "より": ("電車（より）バスのほうが安いです。", "正确：「より」表示比较基准。",
                [("電車（まで）バスのほうが安いです。", "错误：「まで」表示终点。"),
                 ("電車（から）バスのほうが安いです。", "错误：「から」表示起点。"),
                 ("電車（で）バスのほうが安いです。", "错误：「で」表示场所或手段。")]),
        "と": ("友だち（と）映画を見ました。", "正确：「と」表示共同动作对象。",
              [("友だち（を）映画を見ました。", "错误：「を」会把朋友当动作对象。"),
               ("友だち（で）映画を見ました。", "错误：「で」不能表示共同对象。"),
               ("友だち（から）映画を見ました。", "错误：「から」表示起点或来源。")]),
        "も": ("私（も）行きます。", "正确：「も」表示同类追加。",
              [("私（を）行きます。", "错误：「を」不能表示“也”。"),
               ("私（で）行きます。", "错误：「で」表示手段或场所。"),
               ("私（から）行きます。", "错误：「から」表示起点。")]),
        "や": ("机の上に本（や）ノートがあります。", "正确：「や」用于不完全列举。",
              [("机の上に本（を）ノートがあります。", "错误：「を」不能连接列举名词。"),
               ("机の上に本（で）ノートがあります。", "错误：「で」不用于名词列举。"),
               ("机の上に本（から）ノートがあります。", "错误：「から」表示起点。")]),
        "の": ("走る（の）が好きです。", "正确：「の」可以把前面的内容名词化。",
              [("走る（を）が好きです。", "错误：「を」不能把动词短语名词化。"),
               ("走る（で）が好きです。", "错误：「で」表示场所或手段。"),
               ("走る（から）が好きです。", "错误：「から」表示原因或起点。")]),
        "か": ("彼が来る（か）分かりません。", "正确：「か」放在从句中表示疑问或不确定。",
              [("彼が来る（を）分かりません。", "错误：「を」不能放在从句末表示疑问。"),
               ("彼が来る（が）分かりません。", "错误：「が」不能在这里标记疑问内容。"),
               ("彼が来る（ので）分かりません。", "错误：「ので」表示原因，不表示是否。")]),
    }
    if expr in particle_options:
        correct, note, distractors = particle_options[expr]
        return pack(correct, note, distractors)

    if "ておく" in expr or "とく" in expr:
        return pack(
            "旅行の前に、ホテルを予約しておく。",
            "正确：「ておく」表示为了将来预先做好准备。",
            [
                ("昨日から雨が降っておく。", "错误：「降る」不是人为预先准备的动作，不能用「ておく」。"),
                ("駅に着いたら、友だちが待っておく。", "错误：「待つ」这里表示正在等，应用「待っている」。"),
                ("毎朝六時に起きておく。", "错误：日常习惯不自然地说成预先准备。"),
            ],
        )
    if "てある" in expr:
        return pack(
            "机の上に資料が置いてある。",
            "正确：「てある」表示人为动作后的结果状态。",
            [
                ("私は資料を置いてある。", "错误：「てある」通常让对象作主语，不说「私は」。"),
                ("雨が降ってある。", "错误：自然现象不是人为准备后的结果。"),
                ("資料を置いているところです。", "错误：这是正在进行，不是结果状态。"),
            ],
        )
    if "ている" in expr:
        return pack(
            "田中さんは今、電話している。",
            "正确：「ている」表示动作正在进行或状态持续。",
            [
                ("旅行の前に、ホテルを予約している。", "错误：如果表示预先准备，更自然用「予約しておく」。"),
                ("ドアが開けている。", "错误：结果状态一般说「開けてある」或「開いている」。"),
                ("昨日宿題をしている。", "错误：过去完成的动作不能只用现在的「ている」。"),
            ],
        )
    if "てしま" in expr:
        return pack(
            "大切な書類をなくしてしまった。",
            "正确：「てしまう」表示完成，也常带遗憾、后悔语气。",
            [
                ("旅行の前に予約してしまう。", "错误：若强调预先准备，应用「ておく」。"),
                ("毎朝六時に起きてしまう。", "错误：普通习惯不自然地用遗憾完成。"),
                ("友だちを待ってしまう。", "错误：这里不表达遗憾完成，通常说「待っている」。"),
            ],
        )

    close_patterns = [
        (("について", "に関して"), "日本の文化（{x}）、発表します。",
         [("に対して", "错误：「に対して」表示动作面向的对象，不表示话题。"),
          ("によって", "错误：「によって」表示手段、原因或差异。"),
          ("にとって", "错误：「にとって」表示从某人立场看。")],
         f"正确：{expr} 表示话题或讨论对象。"),
        (("に対",), "学生の質問（{x}）、丁寧に答えました。",
         [("について", "错误：「について」表示话题，不表示回答对象。"),
          ("によって", "错误：「によって」表示手段或原因。"),
          ("にとって", "错误：「にとって」表示立场。")],
         f"正确：{expr} 表示动作或态度面向的对象。"),
        (("に基", "をもと"), "調査結果（{x}）、報告書を作成しました。",
         [("について", "错误：「について」表示话题，不表示依据。"),
          ("に対して", "错误：「に対して」表示对象，不表示依据。"),
          ("にとって", "错误：「にとって」表示立场。")],
         f"正确：{expr} 表示依据或基础。"),
        (("に従",), "規則（{x}）、手続きを進めてください。",
         [("につれて", "错误：「につれて」表示随变化而变化。"),
          ("に伴って", "错误：「に伴って」表示伴随变化。"),
          ("について", "错误：「について」表示话题。")],
         f"正确：{expr} 表示按照规则或指示。"),
        (("につれて", "に伴"), "町の人口が増える（{x}）、店も多くなりました。",
         [("に従って", "错误：「に従って」偏向按照规则或指示。"),
          ("について", "错误：「について」表示话题。"),
          ("に対して", "错误：「に対して」表示对象。")],
         f"正确：{expr} 表示随着前项变化，后项也变化。"),
        (("として",), "彼は代表（{x}）、会議に出席しました。",
         [("について", "错误：「について」表示话题。"),
          ("にとって", "错误：「にとって」表示立场。"),
          ("によって", "错误：「によって」表示手段或原因。")],
         f"正确：{expr} 表示身份、资格或立场。"),
        (("ことにする",), "来月からジムに通う（{x}）。",
         [("ことになる", "错误：「ことになる」多表示外部安排。"),
          ("ようになる", "错误：「ようになる」表示状态变化。"),
          ("つもりだ", "错误：「つもりだ」只是个人打算，不是该固定表达。")],
         f"正确：{expr} 表示主语主动决定。"),
        (("ことになる",), "会議で、新しい制度を始める（{x}）。",
         [("ことにする", "错误：「ことにする」表示主动决定。"),
          ("ようにする", "错误：「ようにする」表示努力做到。"),
          ("つもりだ", "错误：「つもりだ」表示个人打算。")],
         f"正确：{expr} 表示外部安排或自然结果。"),
        (("ようにする",), "健康のために、毎日野菜を食べる（{x}）。",
         [("ようになる", "错误：「ようになる」表示状态变化。"),
          ("ことになる", "错误：「ことになる」表示安排或结果。"),
          ("ためになる", "错误：「ためになる」表示有帮助。")],
         f"正确：{expr} 表示有意识地努力做到。"),
        (("ようになる",), "毎日練習して、漢字が読める（{x}）。",
         [("ようにする", "错误：「ようにする」表示努力做到。"),
          ("ことにする", "错误：「ことにする」表示主动决定。"),
          ("ためにする", "错误：「ためにする」不是状态变化表达。")],
         f"正确：{expr} 表示能力或状态发生变化。"),
        (("ほうがいい",), "熱があるなら、今日は早く寝た（{x}）。",
         [("てもいい", "错误：「てもいい」表示许可，不是建议最好做。"),
          ("なければならない", "错误：「なければならない」表示义务，语气过强。"),
          ("ことがある", "错误：「ことがある」表示经验，不表示建议。")],
         f"正确：{expr} 用于提出建议。"),
        (("得る",), "その問題は今後も起こり（{x}）。",
         [("きれる", "错误：「きれる」表示完全做完，不表示可能性。"),
          ("がちだ", "错误：「がちだ」表示倾向，不是可能性判断。"),
          ("べきだ", "错误：「べきだ」表示应该，不表示可能发生。")],
         f"正确：{expr} 表示可能发生。"),
        (("得ない",), "そんなことは普通あり（{x}）。",
         [("得る", "错误：「得る」表示可能，和“不可能”相反。"),
          ("がちだ", "错误：「がちだ」表示倾向，不表示不可能。"),
          ("べきだ", "错误：「べきだ」表示应该。")],
         f"正确：{expr} 表示不可能。"),
    ]
    for keys, frame, alts, note in close_patterns:
        if any(k in expr for k in keys):
            return pack(frame.format(x=expr), note, [(frame.format(x=a), why) for a, why in alts])

    if "原因" in signal or "因为" in signal or "由于" in signal:
        correct = f"大雨（{expr}）、試合は中止になった。"
        return pack(correct, f"正确：{expr} 在这里连接原因和结果。", [
            (f"大雨（{expr}）、試合をしたいです。", "错误：后项不是原因造成的结果，语义不成立。"),
            (f"大雨（{expr}）です。", "错误：后面缺少结果内容，句子结构不完整。"),
            (f"試合は中止になった（{expr}）、大雨です。", "错误：原因和结果顺序倒置，不符合该用法。"),
        ])
    if "条件" in signal or "如果" in signal:
        correct = f"時間がある（{expr}）、一緒に行きましょう。"
        return pack(correct, f"正确：{expr} 用于提出条件。", [
            (f"昨日時間があった（{expr}）、一緒に行きました。", "错误：已发生事实不适合这种条件用法。"),
            (f"時間がある（{expr}）です。", "错误：后项缺少在条件下成立的内容。"),
            (f"時間がないのに（{expr}）、行きました。", "错误：逆接内容里再接目标表达不自然。"),
        ])
    if "逆接" in signal or "转折" in signal or "虽然" in signal or "但是" in signal or "却" in signal:
        correct = f"値段は高い（{expr}）、品質はいい。"
        return pack(correct, f"正确：{expr} 表示前后内容转折或让步。", [
            (f"値段は高い（{expr}）、買いませんでした。", "错误：后项只是顺接结果，不是转折关系。"),
            (f"値段は高い（{expr}）高いです。", "错误：前后没有形成反差。"),
            (f"値段は高い（{expr}）です。", "错误：后项不完整，不能构成转折。"),
        ])
    if "目的" in signal or "为了" in signal:
        correct = f"試験に合格する（{expr}）、毎日復習している。"
        return pack(correct, f"正确：{expr} 表示目的。", [
            (f"試験に合格した（{expr}）、家族が喜んだ。", "错误：前项是已发生结果，不是目的。"),
            (f"試験に合格する（{expr}）です。", "错误：后项缺少为目的而做的行为。"),
            (f"毎日復習している（{expr}）、試験に合格した。", "错误：顺序和语义不符合目的表达。"),
        ])
    if "疑问" in signal or "选择" in signal or "是否" in signal:
        target = ex_target or expr
        correct = f"彼が来る（{target}）分かりません。"
        return pack(correct, f"正确：{target} 在从句中表示疑问或不确定。", [
            (f"彼が来る（{target}）行きます。", "错误：后项不是认知动词，疑问从句连接不自然。"),
            (f"彼が来る（{target}）です。", "错误：句尾结构不完整，不能这样收句。"),
            (f"彼が来た（{target}）、うれしいです。", "错误：这里是原因或事实感想，不是疑问内容。"),
        ])
    if "建议" in signal or "最好" in signal:
        correct = f"熱があるなら、今日は早く寝る（{expr}）。"
        return pack(correct, f"正确：{expr} 用于建议更合适的做法。", [
            (f"昨日早く寝た（{expr}）。", "错误：已经发生的过去事实不适合用来提出建议。"),
            (f"早く寝る（{expr}）です。", "错误：接续和句尾结构不自然。"),
            (f"熱があるなら、早く寝ない（{expr}）。", "错误：语义和建议方向相反。"),
        ])
    if "劝诱" in signal or "誘" in signal or "让我们" in signal:
        target = "ようではないか" if "うではないか" in expr or "ようではないか" in expr else expr
        return pack(
            f"もう一度、みんなで考え（{target}）。",
            f"正确：{target} 用来向听话人提出较郑重的劝诱。",
            [
                (f"昨日、みんなで考え（{target}）。", "错误：已经发生的过去事实不能用来发出劝诱。"),
                (f"私は一人で考え（{target}）。", "错误：劝诱通常面向听话人一起行动，这里语境不合。"),
                (f"考えた（{target}）です。", "错误：接续和句尾结构不自然。"),
            ],
        )
    if "时间" in signal or "場合" in signal or "场合" in signal or "際" in expr:
        target = "際に" if "際" in expr else expr
        return pack(
            f"試験の（{target}）、学生証を見せてください。",
            f"正确：{target} 表示某个时候或场合。",
            [
                (f"試験を受けるための（{target}）、学生証を見せてください。", "错误：前项已经是目的结构，再接该表达不自然。"),
                (f"試験が終わった（{target}）です。", "错误：后项结构不完整，不能这样收句。"),
                (f"学生証の（{target}）、試験を受けます。", "错误：前后语义关系不成立，不是在说明时间场合。"),
            ],
        )
    if "範囲" in signal or "范围" in signal or "评价" in signal or "評価" in signal or "にかけ" in expr or "に限る" in expr:
        target = "にかけては" if "かけ" in expr else ("に限る" if "限る" in expr else expr)
        return pack(
            f"料理の味（{target}）、この店が一番だ。",
            f"正确：{target} 在这里表示评价的范围或方面。",
            [
                (f"料理の味（{target}）、駅へ行きます。", "错误：后项不是评价内容，语义不合。"),
                (f"料理の味（{target}）です。", "错误：后项缺少评价判断，结构不完整。"),
                (f"この店が一番だ（{target}）、料理の味。", "错误：前后顺序和接续不自然。"),
            ],
        )
    if "不必要" in signal or "ないことはない" in expr or "ないこともない" in expr:
        target = "ないことはない" if "ないことはない" in expr else expr
        return pack(
            f"行きたく（{target}）が、今日は忙しい。",
            f"正确：{target} 用双重否定表示并非完全否定。",
            [
                (f"昨日行きたく（{target}）。", "错误：后项缺少转折或补充内容，语义不完整。"),
                (f"学生（{target}）、今日は忙しい。", "错误：前面只接名词，接续不符合该表达。"),
                (f"行きたい（{target}）です。", "错误：肯定形后直接接该表达不自然。"),
            ],
        )

    if ex_target and example_jp and "この文では" not in example_jp:
        alternative_map = {
            "の": [("こと", "错误：「こと」表示抽象事情，这里不能自然替代「の」。"), ("を", "错误：「を」不能名词化前面的内容。"), ("が", "错误：「が」不能名词化前面的内容。")],
            "か": [("を", "错误：「を」不能表示疑问或不确定。"), ("が", "错误：「が」不能表示疑问内容。"), ("ので", "错误：「ので」表示原因，不表示是否。")],
            "が": [("ので", "错误：「ので」表示原因，不表示逆接或铺垫。"), ("なら", "错误：「なら」表示条件。"), ("ために", "错误：「ために」表示目的或原因。")],
            "も": [("は", "错误：「は」只提示主题，不表示追加。"), ("を", "错误：「を」标记动作对象。"), ("だけ", "错误：「だけ」表示限定，不表示“也”。")],
            "ば": [("ので", "错误：「ので」表示原因，不表示条件。"), ("のに", "错误：「のに」表示逆接。"), ("ために", "错误：「ために」表示目的或原因。")],
            "ながら": [("ために", "错误：「ために」表示目的，不表示同时动作。"), ("てから", "错误：「てから」表示先后顺序。"), ("ので", "错误：「ので」表示原因。")],
            "たい": [("た", "错误：「た」表示过去，不表示愿望。"), ("ため", "错误：「ため」表示目的或原因。"), ("こと", "错误：「こと」不能直接表达愿望。")],
            "ならない": [("なくてもいい", "错误：「なくてもいい」表示不必，语义相反。"), ("てはいけない", "错误：「てはいけない」表示禁止。"), ("かもしれない", "错误：「かもしれない」表示可能。")],
        }
        alts = alternative_map.get(ex_target, [
            ("こと", "错误：这是相近形式，但接续或语义不符合这个例句。"),
            ("ために", "错误：这是目的表达，不能替代目标表达。"),
            ("のに", "错误：这是逆接表达，不能替代目标表达。"),
        ])
        correct = example_jp
        distractors = [
            (example_jp.replace(f"（{ex_target}）", f"（{alt}）"), why)
            for alt, why in alts
        ]
        return pack(correct, f"正确：源例句中「{ex_target}」符合该语法点的接续和语义。", distractors)

    # Last fallback for OCR-noisy rows. Do not fabricate a grammar example if the
    # expression cannot be parsed safely; keep the card tied to the target text
    # without creating an incorrect Japanese sentence.
    correct = f"「{expr}」は、このカードで確認する表現です。"
    return pack(correct, f"正确：源条目无法稳定解析时，只确认目标表达「{expr}」本身。", [
        (f"「{expr}」は、必ず名詞だけに接続します。", "错误：无法从源条目断定它只接名词。"),
        (f"「{expr}」は、必ず命令文だけで使います。", "错误：无法从源条目断定它只用于命令文。"),
        (f"「{expr}」は、必ず過去形だけで使います。", "错误：无法从源条目断定它只接过去形。"),
    ])


def merged_cards() -> list[dict[str, object]]:
    rows_by_point = load_source_rows()
    source_rows = source_row_list()
    manual_cards: dict[str, dict[str, object]] = {str(card["point"]): dict(card) for card in CARDS}

    for item in POINTS:
        point = str(item["point"])
        if point not in manual_cards:
            base = rows_by_point.get(point, {})
            manual_cards[point] = {
                    "level": base.get("Level", "N2"),
                    "point": point,
                    "meaning": base.get("MeaningCN", ""),
                    "connection": item["connection"],
                    "explanation": base.get("ExplanationCN", ""),
                    "options": item["options"],
                    "correct_cn": item["cn"],
                    "source": f"{base.get('Book', 'curated sample')} / {base.get('SourcePageImage', '')}".strip(" /"),
                }

    cards: list[dict[str, object]] = []
    for base in source_rows:
        point = base["CleanGrammarPoint"]
        if point in manual_cards:
            card = dict(manual_cards[point])
            card["level"] = base.get("Level") or card.get("level", "Unknown")
            card["meaning"] = card.get("meaning") or base.get("MeaningCN", "")
            card["explanation"] = card.get("explanation") or base.get("ExplanationCN", "")
            card["source"] = f"{base.get('Book', 'curated sample')} / {base.get('SourcePageImage', '')}".strip(" /")
        else:
            card = {
                "level": base.get("Level", "Unknown"),
                "point": point,
                "meaning": base.get("MeaningCN", ""),
                "connection": base.get("Connection", ""),
                "explanation": base.get("ExplanationCN", ""),
                "options": natural_generic_options(
                    point,
                    base.get("MeaningCN", ""),
                    base.get("FunctionCategory", ""),
                    base.get("ExampleJP", ""),
                    base.get("Connection", ""),
                ),
                "correct_cn": base.get("ExampleCN", "") or f"这句话用于练习“{point}”的用法。",
                "source": f"{base.get('Book', 'curated sample')} / {base.get('SourcePageImage', '')}".strip(" /"),
            }
        cards.append(card)
    return cards


async def synthesize(text: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(str(path))
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"empty audio: {path}")


async def build_audio(jobs: list[tuple[str, Path]]) -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    remaining = [(text, path) for text, path in jobs if not path.exists() or path.stat().st_size == 0]
    if not remaining:
        print("Audio already complete")
        return

    semaphore = asyncio.Semaphore(8)
    completed = 0
    total = len(remaining)

    async def run_one(text: str, path: Path) -> None:
        nonlocal completed
        async with semaphore:
            for attempt in range(1, 4):
                try:
                    await synthesize(text, path)
                    break
                except Exception:
                    if path.exists() and path.stat().st_size == 0:
                        path.unlink()
                    if attempt == 3:
                        raise
                    await asyncio.sleep(1.5 * attempt)
        completed += 1
        if completed == 1 or completed % 50 == 0 or completed == total:
            print(f"audio {completed}/{total} {path.name}")

    await asyncio.gather(*(run_one(text, path) for text, path in remaining))


def build_rows() -> tuple[list[dict[str, str]], list[tuple[str, Path]]]:
    rows: list[dict[str, str]] = []
    jobs: list[tuple[str, Path]] = []
    letters = ["A", "B", "C", "D"]
    for idx, card in enumerate(merged_cards(), start=1):
        card_id = f"JP-GRAMMAR-QUALITY-MCQ-{idx:02d}"
        rng = random.Random(idx * 20260716)
        options = list(card["options"])
        rng.shuffle(options)
        correct_index = next(i for i, option in enumerate(options) if option[1])
        correct_letter = letters[correct_index]
        correct_example = options[correct_index][0]
        rationale = "<br>".join(f"{letter}. {note}" for letter, (_, _, note) in zip(letters, options))

        grammar_audio = audio_name(card_id, "grammar")
        jobs.append((safe_tts_text(strip_parentheses_for_tts(str(card["point"]).replace("～", ""))), MEDIA_DIR / grammar_audio))

        row = {
            "CardID": card_id,
            "Level": str(card["level"]),
            "GrammarPoint": str(card["point"]),
            "GrammarAudio": sound(grammar_audio),
            "MeaningCN": str(card["meaning"]),
            "ExplanationCN": str(card["explanation"]),
            "Connection": str(card["connection"]),
            "CorrectOption": correct_letter,
            "CorrectExample": correct_example,
            "CorrectExampleCN": str(card.get("correct_cn") or CORRECT_CN.get(str(card["point"]), "")),
            "Rationale": rationale,
            "Source": str(card.get("source") or "curated quality sample"),
            "Tags": f"jp_grammar quality_mcq nanami {str(card['level']).replace('/', '_')}",
        }
        for letter, option in zip(letters, options):
            file_name = audio_name(card_id, f"option_{letter}")
            row[f"Option{letter}"] = option[0]
            row[f"Option{letter}Audio"] = manual_audio(file_name)
            jobs.append((safe_tts_text(strip_parentheses_for_tts(option[0])), MEDIA_DIR / file_name))
        rows.append(row)
    return rows, jobs


def write_apkg(rows: list[dict[str, str]], media_files: list[Path], path: Path, deck_name: str, deck_id: int) -> None:
    model = genanki.Model(
        1707160201,
        "JP Grammar Quality MCQ Nanami",
        fields=[{"name": field} for field in FIELDS],
        templates=[{"name": "Quality MCQ", "qfmt": FRONT_TEMPLATE, "afmt": BACK_TEMPLATE}],
        css=CSS,
    )
    deck = genanki.Deck(deck_id, deck_name)
    wanted_media = set()
    for row in rows:
        wanted_media.update(re.findall(r"\[sound:([^\]]+)\]", "\x1f".join(row.values())))
        wanted_media.update(re.findall(r'src="([^"]+)"', "\x1f".join(row.values())))
        deck.add_note(
            genanki.Note(
                model=model,
                fields=[row[field] for field in FIELDS],
                tags=row["Tags"].split(),
                guid=hashlib.sha1(row["CardID"].encode("utf-8")).hexdigest(),
            )
        )
    media_by_name = {media_path.name: media_path for media_path in media_files}
    selected = [
        str(media_by_name[name])
        for name in sorted(wanted_media)
        if name in media_by_name and media_by_name[name].exists() and media_by_name[name].stat().st_size > 0
    ]
    genanki.Package(deck, media_files=selected).write_to_file(str(path))


def write_tsv(rows: list[dict[str, str]], path: Path, deck_name: str) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        fh.write("#separator:tab\n")
        fh.write("#html:true\n")
        fh.write(f"#deck:{deck_name}\n")
        writer = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_preview(rows: list[dict[str, str]]) -> None:
    css = CSS.replace(".card {", "body {").replace(".card-wrap, .answer {", ".preview-card {")
    cards = []
    for row in rows:
        choices = "\n".join(
            f'<div class="choice"><span class="letter">{letter}</span><span>{html.escape(row[f"Option{letter}"])}</span><span class="speaker">mp3</span></div>'
            for letter in "ABCD"
        )
        cards.append(
            f"""
<section class="preview-card">
  <div class="topline"><span class="level">{html.escape(row['Level'])}</span></div>
  <div class="grammar">{html.escape(row['GrammarPoint'])}</div>
  <div class="choices">{choices}</div>
  <div class="correct">正确答案：{html.escape(row['CorrectOption'])}</div>
  <div class="meaning">{html.escape(row['MeaningCN'])}</div>
  <div class="block">{row['Rationale']}</div>
</section>"""
        )
    with PREVIEW.open("w", encoding="utf-8-sig") as fh:
        fh.write('<!doctype html><html><head><meta charset="utf-8"><title>Quality MCQ Preview</title><style>')
        fh.write(css)
        fh.write(".preview-card{background:#f7f7f4;border:1px solid #dedbd2;border-radius:8px;margin:18px auto;max-width:820px;padding:18px 20px;}")
        fh.write("</style></head><body>")
        fh.write("\n".join(cards))
        fh.write("</body></html>")


async def main(skip_audio: bool = False) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows, jobs = build_rows()
    if not skip_audio:
        await build_audio(jobs)
    media_files = [path for _, path in jobs]

    outputs: list[Path] = []
    write_apkg(rows, media_files, ALL_APKG, "JP Grammar Quality MCQ Nanami", 1707160202)
    outputs.append(ALL_APKG)
    write_tsv(rows, ALL_TSV, "JP Grammar Quality MCQ Nanami")
    outputs.append(ALL_TSV)

    by_level: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_level.setdefault(row["Level"], []).append(row)
    for level, level_rows in sorted(by_level.items()):
        slug = tagify(level).replace("_", "-")
        deck_name = f"JP Grammar {level} Quality MCQ Nanami"
        apkg = EXPORT_DIR / f"anki_grammar_{slug}_quality_mcq_nanami_mp3.apkg"
        tsv = EXPORT_DIR / f"anki_grammar_{slug}_quality_mcq_nanami_mp3.tsv"
        write_apkg(level_rows, media_files, apkg, deck_name, deck_id_for(deck_name))
        write_tsv(level_rows, tsv, deck_name)
        outputs.extend([apkg, tsv])

    write_preview(rows)
    outputs.append(PREVIEW)
    for path in outputs:
        print(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-audio", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(skip_audio=args.skip_audio))
