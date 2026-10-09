"""Offscreen integration tests using real WAV files and SDL's dummy audio."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
import tempfile
import unittest
import wave
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from player import Player

app = QApplication.instance() or QApplication([])


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base/'music'
        self.root.mkdir()
        for n in range(3):
            with wave.open(str(self.root/f'{n}.wav'),'wb') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(8000)
                f.writeframes(b'\0\0'*80000)
        self.player = Player(self.base/'player.db',auto_start=False)
        self.player.show()
        self.player.open_folder(str(self.root))
        app.processEvents()

    def tearDown(self):
        self.player.close()
        app.processEvents()
        self.temp.cleanup()

    def test_play_pause_delete_restore_and_classification(self):
        p = self.player
        self.assertTrue(p.playing)
        self.assertEqual(p.count_label.text(),'1/3')
        p.toggle_play()
        self.assertTrue(p.paused)
        p.toggle_play()
        p.next_track()
        current = p.current
        p.delete_previous()
        self.assertEqual(p.current,current)
        self.assertTrue(p.playing)
        self.assertFalse((self.root/'0.wav').exists())
        p.restore()
        self.assertTrue((self.root/'0.wav').exists())
        started = p.started_at
        stream = p.audio_stream
        p.classify('metal')
        self.assertEqual(p.current, current)
        self.assertEqual(p.started_at, started)
        self.assertIs(p.audio_stream, stream)
        self.assertTrue(p.playing)
        self.assertFalse(Path(current).exists())
        import pygame
        self.assertTrue(pygame.mixer.music.get_busy())
        self.assertTrue((self.base/'classify'/'metal'/'1.wav').exists())
        pygame.mixer.music.stop()
        p.tick()
        self.assertTrue(p.current.endswith('2.wav'))
        p.delete_previous()
        self.assertEqual(p.log_edit.toPlainText(),'Already classified; cannot delete')
        p.delete_current()
        self.assertTrue(p.current.endswith('0.wav'))
        p.restore()
        self.assertTrue((self.root/'2.wav').exists())
        self.assertTrue(p.current.endswith('0.wav'))

    def test_classify_paused_and_last_track(self):
        p = self.player
        p.toggle_play()
        p.classify('metal')
        self.assertTrue(p.paused)
        self.assertFalse(p.playing)
        p.classify('blues')
        self.assertEqual(p.log_edit.toPlainText(), 'Track already classified')
        self.assertFalse((self.base/'classify'/'blues').exists())
        p.toggle_play()
        self.assertTrue(p.playing)
        p.next_track()
        self.assertTrue(p.current.endswith('1.wav'))
        p.classify('metal')
        p.next_track()
        p.classify('metal')
        self.assertEqual(p.library.tracks, [])
        self.assertTrue(p.playing)
        import pygame
        pygame.mixer.music.stop()
        p.tick()
        self.assertIsNone(p.current)
        self.assertFalse(p.playing)
        self.assertIsNone(p.audio_stream)

    def test_random_previous_tracks_actual_history(self):
        p = self.player
        p.set_mode('RANDOM')
        first = p.current
        p.next_track()
        second = p.current
        p.next_track()
        third = p.current
        self.assertEqual(len({first,second,third}),3)
        p.previous()
        self.assertEqual(p.current,second)
        p.delete_previous()
        self.assertFalse(Path(third).exists())
        self.assertTrue(Path(second).exists())
        p.previous()
        self.assertEqual(p.current,first)

    def test_layout_icons_and_end_of_track(self):
        p = self.player
        for button in p.buttons.values():
            self.assertFalse(button.icon().isNull())
        p.layout_controls(True)
        self.assertEqual(p.width(),360)
        self.assertFalse(p.buttons['delete'].isVisible())
        self.assertTrue(p.buttons['restore'].isVisible())
        for key in ['show','hide','seq','restore','random']:
            self.assertTrue(p.rect().contains(p.buttons[key].geometry()))
        p.layout_controls(False)
        self.assertTrue(p.log_edit.isVisible())
        p.buttons['random'].click()
        p.buttons['random'].click()
        self.assertTrue(p.buttons['random'].isChecked())
        self.assertFalse(p.buttons['seq'].isChecked())
        p.set_mode('SEQ')
        import pygame
        pygame.mixer.music.stop()
        p.tick()
        self.assertTrue(p.current.endswith('1.wav'))
        p.change_volume(1000)
        self.assertEqual(p.volume,100)
        p.change_volume(-1000)
        self.assertEqual(p.volume,0)


if __name__=='__main__':
    unittest.main()
