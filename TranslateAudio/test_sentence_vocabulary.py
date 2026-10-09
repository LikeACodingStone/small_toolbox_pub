"""Run with the project's Python: -m unittest discover -s TranslateAudio."""
import ast
import io
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import translate_audio as audio


class SentenceVocabularyTests(unittest.TestCase):
    def test_grouped_sample_keeps_only_words_in_current_sentence(self):
        sample = next((Path(__file__).resolve().parents[1] / "Output_Sample").glob("*.md"))
        rows = audio.parse_md_segments(sample.read_text())
        self.assertEqual(audio.sentence_vocabulary(rows[1]), "songwriters: 作词家")
        thank_you = next(row for row in rows if row["english"] == "Thank you.")
        self.assertEqual(audio.sentence_vocabulary(thank_you), "")

    def test_exact_words_and_apostrophes(self):
        row = {
            "start": 0,
            "english": "Songwriters don't re-acclaim a composer's work.",
            "translation": "Vocabulary: song: 歌; songwriter: 作者; songwriters: 作者们; "
                           "acclaim: 赞扬; composer: 作曲家; DON’T: 不要",
        }
        self.assertEqual(audio.sentence_vocabulary(row), "songwriters: 作者们; DON’T: 不要")

    def test_rejects_unstructured_translation(self):
        self.assertEqual(audio.sentence_vocabulary({
            "start": 0, "english": "Thank you.", "translation": "谢谢你。",
        }), "")

    def test_markdown_and_fullwidth_delimiters(self):
        self.assertEqual(audio.sentence_vocabulary({
            "start": 0, "english": "An acclaimed songwriter.",
            "translation": "Vocabulary: **acclaimed**： 著名； songwriter: 作词家",
        }), "acclaimed: 著名; songwriter: 作词家")

    def test_process_preserves_audio_boundaries_and_passes_filtered_tts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "episode.mp3"
            markdown = root / "episode.md"
            markdown.write_text(
                "**[0.00s] English:** An acclaimed songwriter.\n**Translation:**\n\n"
                "**[6.84s] English:** Influential songwriters.\n"
                "**Translation:** Vocabulary: acclaimed: 著名; songwriters: 作词家\n\n"
                "**[12.12s] English:** Thank you.\n**Translation:** Vocabulary: jimmy: 吉米\n",
            )
            output = root / "episode_TranslateAudio.mp3"
            output.write_bytes(b"old output")
            with patch.object(audio, "run_tts_limited", new_callable=AsyncMock, return_value=["tts.mp3"]) as tts, \
                 patch.object(audio, "require_ffmpeg", return_value=("ffmpeg", "ffprobe")), \
                 patch.object(audio, "get_audio_duration_seconds", return_value=20), \
                 patch.object(audio, "write_filtered_concat") as combine:
                self.assertEqual(audio.process_one(source, root, root, "_TranslateAudio"), "skipped")
                tts.assert_not_called()
                self.assertEqual(audio.process_one(source, root, root, "_TranslateAudio", force=True), "ok")
                selected = combine.call_args.args[0]
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0]["start"], 6.84)
                self.assertEqual(selected[0]["next_start"], 12.12)
                self.assertEqual(selected[0]["translation"], "songwriters: 作词家")
                self.assertEqual(tts.call_args.args[0], selected)

    def test_new_markdown_translates_each_sentence_separately(self):
        # Isolate the writer from Whisper/GPU/model initialization. Exercise the
        # actual writer functions while replacing only the translation service.
        path = Path(__file__).resolve().parents[1] / "InsertSpeech" / "transcribe_module.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        names = {"write_markdown_segment", "write_segment", "write_segment_group"}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        calls = []

        def translate(start, english, **kwargs):
            calls.append((start, english, kwargs))
            return "Vocabulary: acclaimed: 著名" if "acclaimed" in english else ""

        namespace = {"RECENT_TRANSLATION_WINDOW_SECONDS": 80, "build_translation_text": translate}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
        handle = io.StringIO()
        recent = {}
        namespace["write_segment_group"](
            handle, [(0, "An acclaimed songwriter."), (6.84, "Thank you.")],
            recent_translations=recent,
        )
        rows = audio.parse_md_segments(handle.getvalue())
        self.assertEqual(rows[0]["translation"], "Vocabulary: acclaimed: 著名")
        self.assertEqual(rows[1]["translation"], "")
        self.assertEqual([call[:2] for call in calls], [(0, "An acclaimed songwriter."), (6.84, "Thank you.")])
        self.assertTrue(all(call[2]["recent_translations"] is recent for call in calls))

    def test_force_removes_stale_output_when_all_vocabulary_is_unmatched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "episode.md").write_text(
                "**[0.00s] English:** Thank you.\n**Translation:** Vocabulary: jimmy: 吉米\n",
            )
            output = root / "episode_TranslateAudio.mp3"
            output.write_bytes(b"old mismatched output")
            with patch.object(audio, "run_tts_limited", new_callable=AsyncMock) as tts:
                self.assertEqual(audio.process_one(root / "episode.mp3", root, root, "_TranslateAudio", force=True), "no_vocabulary")
                tts.assert_not_called()
                self.assertFalse(output.exists())


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    unittest.main()
