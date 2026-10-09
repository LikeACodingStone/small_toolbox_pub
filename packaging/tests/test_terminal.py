import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminal import add_terminal_entry


class TerminalTests(unittest.TestCase):
    def test_manual_shell_and_terminal_dispatch(self):
        for code in ('A001', 'A003'):
            with self.subTest(code=code), tempfile.TemporaryDirectory(prefix='release space ') as folder:
                root = Path(folder)
                add_terminal_entry(root, code)
                # A job sentinel must never run merely from opening the shell.
                for name in ('podcast', 'run'):
                    p = root / name
                    p.write_text('#!/bin/sh\ntouch job-started\n')
                    p.chmod(0o755)
                proc = subprocess.run([root / 'open-terminal', '--shell'],
                    input='printf "CWD=%s\\n" "$PWD"\nfalse\nprintf "STILL_OPEN\\n"\nexit\n',
                    text=True, capture_output=True, cwd='/tmp', timeout=10)
                self.assertIn('CWD=' + str(root), proc.stdout)
                self.assertIn('STILL_OPEN', proc.stdout)
                self.assertFalse((root / 'job-started').exists())
                terminal = root / 'fake terminal'
                terminal.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$CAPTURE"\n')
                terminal.chmod(0o755)
                env = dict(os.environ, DISPLAY=':test', TOOLBOX_TERMINAL=str(terminal), CAPTURE=str(root / 'args'))
                subprocess.run([root / 'open-terminal'], env=env, check=True)
                self.assertEqual((root / 'args').read_text().splitlines(), ['-e', str(root / 'open-terminal'), '--shell'])
                env.pop('DISPLAY', None)
                env.pop('WAYLAND_DISPLAY', None)
                proc = subprocess.run([root / 'open-terminal'], env=env, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 1)
                self.assertIn('--shell', proc.stderr)

    def test_ui_tools_have_no_terminal_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            for code in ('A002', 'A004'):
                add_terminal_entry(Path(folder), code)
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
