from __future__ import annotations

import asyncio
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
SOURCE = OUT_DIR / "anki_grammar_cleaned_enriched.csv"
MEDIA_DIR = OUT_DIR / "nanami_sample_media"
VOICE = "ja-JP-NanamiNeural"

APKG = OUT_DIR / "anki_grammar_sample_10_mcq_nanami_mp3.apkg"
TSV = OUT_DIR / "anki_grammar_sample_10_mcq_nanami_mp3.tsv"
PREVIEW = OUT_DIR / "anki_grammar_sample_10_mcq_nanami_preview.html"
TEMPLATE = OUT_DIR / "anki_grammar_sample_10_mcq_nanami_template.html"


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


def load_source_rows() -> dict[str, dict[str, str]]:
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as fh:
        return {row["CleanGrammarPoint"]: row for row in csv.DictReader(fh)}


def audio_file_name(card_id: str, slot: str) -> str:
    safe_slot = re.sub(r"[^A-Za-z0-9_]+", "_", slot)
    return f"{card_id.lower()}_{safe_slot}.mp3"


def manual_audio_control(file_name: str) -> str:
    return f'<audio controls preload="none" src="{html.escape(file_name, quote=True)}"></audio>'


async def synthesize(text: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(str(path))


async def ensure_audio(audio_jobs: list[tuple[str, Path]]) -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    for index, (text, path) in enumerate(audio_jobs, start=1):
        print(f"[{index}/{len(audio_jobs)}] {path.name}")
        await synthesize(text, path)


def build_rows() -> tuple[list[dict[str, str]], list[tuple[str, Path]]]:
    source = load_source_rows()
    rows: list[dict[str, str]] = []
    audio_jobs: list[tuple[str, Path]] = []
    letters = ["A", "B", "C", "D"]

    for idx, item in enumerate(POINTS, start=1):
        base = source[item["point"]]
        card_id = f"JP-GRAMMAR-MCQ-NANAMI-{idx:02d}"
        rng = random.Random(idx * 20260711)
        options = list(item["options"])
        rng.shuffle(options)

        correct_index = next(index for index, option in enumerate(options) if option[1])
        correct_letter = letters[correct_index]
        correct_example = options[correct_index][0]
        rationale = "<br>".join(f"{letter}. {note}" for letter, (_, _, note) in zip(letters, options))

        grammar_audio_name = audio_file_name(card_id, "grammar")
        grammar_audio_path = MEDIA_DIR / grammar_audio_name
        grammar_tts_text = strip_parentheses_for_tts(base["CleanGrammarPoint"].replace("～", ""))
        audio_jobs.append((grammar_tts_text, grammar_audio_path))

        row = {
            "CardID": card_id,
            "Level": base["Level"],
            "GrammarPoint": base["CleanGrammarPoint"],
            "GrammarAudio": f"[sound:{grammar_audio_name}]",
            "MeaningCN": base["MeaningCN"],
            "ExplanationCN": base["ExplanationCN"],
            "Connection": item["connection"],
            "CorrectOption": correct_letter,
            "CorrectExample": correct_example,
            "CorrectExampleCN": item["cn"],
            "Rationale": rationale,
            "Source": f"{base['Book']} / {base['SourcePageImage']}",
            "Tags": f"jp_grammar sample mcq nanami_mp3 {base['Level'].replace('/', '_')}",
        }

        for letter, option in zip(letters, options):
            audio_name = audio_file_name(card_id, f"option_{letter}")
            audio_path = MEDIA_DIR / audio_name
            audio_text = strip_parentheses_for_tts(option[0])
            row[f"Option{letter}"] = option[0]
            row[f"Option{letter}Audio"] = manual_audio_control(audio_name)
            audio_jobs.append((audio_text, audio_path))

        rows.append(row)
    return rows, audio_jobs


def write_tsv(rows: list[dict[str, str]]) -> None:
    with TSV.open("w", encoding="utf-8-sig", newline="") as fh:
        fh.write("#separator:tab\n")
        fh.write("#html:true\n")
        fh.write("#deck:JP Grammar Sample 10 MCQ Nanami\n")
        writer = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_apkg(rows: list[dict[str, str]], media_paths: list[Path]) -> None:
    model = genanki.Model(
        1707112046,
        "JP Grammar MCQ Nanami MP3 Sample",
        fields=[{"name": field} for field in FIELDS],
        templates=[
            {
                "name": "Grammar MCQ Nanami MP3",
                "qfmt": FRONT_TEMPLATE,
                "afmt": BACK_TEMPLATE,
            }
        ],
        css=CSS,
    )
    deck = genanki.Deck(1707112047, "JP Grammar Sample 10 MCQ Nanami")
    for row in rows:
        deck.add_note(
            genanki.Note(
                model=model,
                fields=[row[field] for field in FIELDS],
                tags=row["Tags"].split(),
                guid=hashlib.sha1(row["CardID"].encode("utf-8")).hexdigest(),
            )
        )
    genanki.Package(deck, media_files=[str(path) for path in media_paths]).write_to_file(str(APKG))


def write_template() -> None:
    with TEMPLATE.open("w", encoding="utf-8-sig") as fh:
        fh.write("<!-- Front Template -->\n")
        fh.write(FRONT_TEMPLATE.strip())
        fh.write("\n\n<!-- Back Template -->\n")
        fh.write(BACK_TEMPLATE.strip())
        fh.write("\n\n<!-- Styling -->\n<style>\n")
        fh.write(CSS.strip())
        fh.write("\n</style>\n")


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
</section>"""
        )
    with PREVIEW.open("w", encoding="utf-8-sig") as fh:
        fh.write('<!doctype html><html><head><meta charset="utf-8"><title>Anki Grammar Nanami MCQ Sample</title><style>')
        fh.write(css)
        fh.write(".preview-card{background:#f7f7f4;border:1px solid #dedbd2;border-radius:8px;margin:18px auto;max-width:820px;padding:18px 20px;}")
        fh.write("</style></head><body>")
        fh.write("\n".join(cards))
        fh.write("</body></html>")


async def main() -> None:
    rows, audio_jobs = build_rows()
    await ensure_audio(audio_jobs)
    media_paths = [path for _, path in audio_jobs]
    write_apkg(rows, media_paths)
    write_tsv(rows)
    write_template()
    write_preview(rows)
    for path in [APKG, TSV, TEMPLATE, PREVIEW]:
        print(path)


if __name__ == "__main__":
    asyncio.run(main())
