import tempfile
import unittest
from pathlib import Path
from library import Library


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        self.root.mkdir()
        self.db = self.base / 'test.db'
        self.lib = Library(self.db)

    def tearDown(self):
        self.lib.close()
        self.temp.cleanup()

    def songs(self, count):
        for n in range(count):
            (self.root / f'{n:02d}.mp3').write_bytes(f'audio-{n}'.encode())
        self.lib.open(self.root)
        return self.lib.tracks.copy()

    def test_opus_scan_case_insensitive_and_trash_excluded(self):
        album = self.root / 'album'
        album.mkdir()
        expected = [self.root / 'track.opus', album / 'TRACK.OPUS']
        for path in expected:
            path.write_bytes(b'scan-only fixture')
        trash = self.root / 'tmp_trash'
        trash.mkdir()
        (trash / 'deleted.opus').write_bytes(b'excluded')
        self.lib.open(self.root)
        self.assertEqual(set(self.lib.tracks), {str(p) for p in expected})

    def test_classify_collision_and_history(self):
        song = self.songs(1)[0]
        self.lib.played(song)
        target = self.base / 'classify' / 'metal'
        target.mkdir(parents=True)
        (target/'00.mp3').write_bytes(b'existing')
        moved = self.lib.classify(song,'metal')
        self.assertEqual(moved.name,'00 (1).mp3')
        self.assertEqual(moved.read_bytes(),b'audio-0')
        self.assertEqual((target/'00.mp3').read_bytes(),b'existing')
        self.assertFalse(Path(song).exists())
        self.assertEqual(self.lib.history[-1]['status'],'classified')
        self.assertEqual(self.lib.tracks,[])

    def test_trash_limit_lifo_restart_and_scan_exclusion(self):
        songs = self.songs(12)
        for path in songs:
            self.lib.delete(path)
        self.assertEqual(len(list((self.root/'tmp_trash').iterdir())),10)
        self.lib.scan()
        self.assertEqual(self.lib.tracks,[])
        self.lib.close()
        self.lib = Library(self.db)
        self.lib.open(self.root)
        restored = [str(self.lib.restore()) for _ in range(10)]
        self.assertEqual(restored,list(reversed(songs[2:])))
        self.assertIsNone(self.lib.restore())
        self.assertFalse(Path(songs[0]).exists())
        self.assertEqual(Path(songs[-1]).read_bytes(),b'audio-11')

    def test_restore_nested_original_collision_and_root_isolation(self):
        nested = self.root/'album'
        nested.mkdir()
        song = nested/'song.mp3'
        song.write_bytes(b'original')
        self.lib.open(self.root)
        self.lib.delete(str(song))
        song.write_bytes(b'new')
        other = self.base/'other'
        other.mkdir()
        self.lib.open(other)
        self.assertIsNone(self.lib.restore())
        self.lib.open(self.root)
        restored = self.lib.restore()
        self.assertEqual(restored,nested/'song (1).mp3')
        self.assertEqual(restored.read_bytes(),b'original')
        self.assertEqual(song.read_bytes(),b'new')

    def test_random_round_restart_and_boundary(self):
        songs = self.songs(8)
        first = self.lib.next(None,True)
        self.lib.played(first)
        self.lib.close()
        self.lib = Library(self.db)
        self.assertEqual(self.lib.open(self.root),first)
        current = first
        self.lib.played(current)
        seen = [first]
        for _ in range(7):
            current = self.lib.next(current,True)
            seen.append(current)
            self.lib.played(current)
        self.assertEqual(set(seen),set(songs))
        self.assertEqual(len(set(seen)),8)
        following = self.lib.next(current,True)
        self.assertNotEqual(following,current)

    def test_single_track_round_and_missing_source(self):
        song = self.songs(1)[0]
        for _ in range(3):
            self.assertEqual(self.lib.next(song,True),song)
            self.lib.played(song)
        Path(song).unlink()
        with self.assertRaises(FileNotFoundError):
            self.lib.delete(song)
        self.assertEqual(self.lib.db.execute('SELECT count(*) FROM trash').fetchone()[0],0)


if __name__=='__main__':
    unittest.main()
