from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package


class SourceTests(unittest.TestCase):
    def test_flat_source_preferred_and_nested_recovery_supported(self):
        for code, branch in package.BRANCHES.items():
            with self.subTest(branch=branch), tempfile.TemporaryDirectory(prefix='source space ') as folder:
                base = Path(folder)
                marker = ('InsertSpeech/main_batch.py' if code == 'A001'
                          else package.TOOLS[code][1][0] + '.py')
                nested = base / package.TOOLS[code][0]
                for source in (base, nested):
                    path = source / marker
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                registry = f'worktree {base}\0branch refs/heads/{branch}\0\0'
                with patch.object(package.subprocess, 'check_output', side_effect=[registry, branch]):
                    self.assertEqual(package.source_for(code, base), base)
                (base / marker).unlink()
                with patch.object(package.subprocess, 'check_output', side_effect=[registry, branch]):
                    self.assertEqual(package.source_for(code, base), nested)

    def test_fallback_rejects_wrong_branch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'English02'
            source.mkdir()
            (source / 'app_ui.py').touch()
            with patch.object(package.subprocess, 'check_output', side_effect=['', 'main']):
                with self.assertRaisesRegex(RuntimeError, 'expected branch English02_SubtitlesToMobi'):
                    package.source_for('A002', root)


if __name__ == '__main__':
    unittest.main()
