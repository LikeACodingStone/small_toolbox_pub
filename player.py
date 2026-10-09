"""Windows/Linux music classifier. See run_player.bat and run_player.sh."""
import os
import sys
import time
import shutil
import tempfile
from pathlib import Path

# Some xrdp/MATE sessions omit this variable even though the user audio
# server is running. SDL needs it to discover PipeWire's PulseAudio socket.
if sys.platform.startswith('linux') and not os.environ.get('XDG_RUNTIME_DIR'):
    runtime = Path('/run/user') / str(os.getuid())
    if runtime.is_dir() and runtime.stat().st_uid == os.getuid():
        os.environ['XDG_RUNTIME_DIR'] = str(runtime)

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame
from mutagen import File as AudioMetadata
from PyQt5.QtCore import Qt, QTimer, QSize, QRectF
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QFileDialog, QLabel, QPushButton, QTextEdit, QWidget

from library import Library, STYLES

BASE = Path(__file__).resolve().parent
ICONS = BASE / 'Icons'
UI_FONT = 'Segoe UI' if sys.platform == 'win32' else 'DejaVu Sans'


def data_directory():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'QMediaClassifier'
    xdg = Path(os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local' / 'share'))
    if not xdg.is_absolute():
        xdg = Path.home() / '.local' / 'share'
    return xdg / 'QMediaClassifier'


class FittedText(QTextEdit):
    def __init__(self, parent, path=False):
        super().__init__(parent)
        self.path_mode = path
        self.full_text = ''
        self.setReadOnly(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.NoWrap)
        self.document().setDocumentMargin(2)
        self.setStyleSheet('QTextEdit { background:#b0e0e6; border:1px solid #657d85; border-radius:4px; color:#303030; padding:1px; }')

    def show_text(self, value):
        self.full_text = str(value)
        self.setToolTip(self.full_text)
        self.fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def fit(self):
        if not hasattr(self, 'full_text'):
            return
        value = self.full_text
        font = QFont(UI_FONT, 9)
        space = max(1, self.viewport().width() - 8)
        if self.path_mode:
            shown = value
            while QFontMetrics(font).horizontalAdvance(shown) > space:
                parts = shown.replace('\\', '/').split('/')
                if len(parts) <= 1:
                    shown = QFontMetrics(font).elidedText(shown, Qt.ElideLeft, space)
                    break
                shown = '/'.join(parts[1:])
        else:
            for spacing in (100, 95, 90, 85, 80):
                font.setLetterSpacing(QFont.PercentageSpacing, spacing)
                if QFontMetrics(font).horizontalAdvance(value) <= space:
                    break
            while QFontMetrics(font).horizontalAdvance(value) > space and font.pointSizeF() > 7:
                font.setPointSizeF(font.pointSizeF() - 0.5)
            shown = QFontMetrics(font).elidedText(value, Qt.ElideRight, space)
        self.setFont(font)
        self.setPlainText(shown)


class Player(QWidget):
    def __init__(self, database=None, auto_start=True):
        super().__init__()
        if database is None:
            data = data_directory()
            data.mkdir(parents=True, exist_ok=True)
            database = data / 'player.db'
        self.library = Library(database)
        self.current = None
        self.audio_stream = None
        self.classified_path = None
        self.successors = []
        self.duration = 0
        self.elapsed = 0
        self.started_at = 0
        self.playing = False
        self.paused = False
        self.audio_ready = False
        self.failed = set()
        self.back_stack = []
        self.mode = self.library.get('mode', 'SEQ')
        self.volume = self.library.get('volume', 50)
        self.compact = False
        self.drag_offset = None
        self.buttons = {}
        self.setWindowTitle('QMediaPlayer')
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.make_ui()
        try:
            pygame.mixer.init()
            pygame.mixer.music.set_volume(self.volume / 100)
            self.audio_ready = True
        except pygame.error as exc:
            self.log('Audio unavailable', str(exc))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(150)
        self.layout_controls(False)
        self.update_mode()
        self.update_labels()
        if auto_start:
            QTimer.singleShot(0, self.startup)

    def make_button(self, key, label, icon, callback, width=55, height=29):
        button = QPushButton(self)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setFixedSize(width, height)
        path = ICONS / (icon + '.png')
        if path.exists():
            button.setIcon(QIcon(str(path)))
            button.setIconSize(QSize(width, height))
        else:
            button.setText(label)
        button.setStyleSheet('QPushButton {border:0; padding:0; background:transparent; border-radius:4px;} QPushButton:pressed {border:2px solid #e64b42;} QPushButton:disabled {background:#a0a0a0;}')
        button.clicked.connect(callback)
        self.buttons[key] = button
        return button

    def make_ui(self):
        for style in STYLES:
            self.make_button(style, style, style.upper(), lambda checked=False, s=style: self.classify(s),95)
        specs = [
            ('vol_down','Volume -10%','VOL-',lambda: self.change_volume(-10),55),
            ('vol_up','Volume +10%','VOL+',lambda: self.change_volume(10),55),
            ('previous','Previous track','PlayPre',self.previous,78),
            ('play','Play / Pause','Play',self.toggle_play,60),
            ('next','Next track','PlayNext',self.next_track,79),
            ('show','Show all controls','SHOW',lambda: self.layout_controls(False),55),
            ('hide','Hide extra controls','HIDE',lambda: self.layout_controls(True),55),
            ('seq','Sequential mode','SEQ',lambda: self.set_mode('SEQ'),78),
            ('restore','Restore last deleted track','RESTORE',self.restore,60),
            ('random','Random mode','RANDOM',lambda: self.set_mode('RANDOM'),79),
            ('delete','Delete current track','DEL',self.delete_current,55),
            ('delete_previous','Delete previous track','DEL_PRE',self.delete_previous,55),
            ('open','Open music folder','OPEN',self.choose_folder,55),
        ]
        for key,label,icon,callback,width in specs:
            self.make_button(key,label,icon,callback,width)
        self.make_button('exit','Exit','EXIT',self.close,30,30)
        self.time_label = self.make_label()
        self.total_label = self.make_label()
        self.count_label = self.make_label()
        self.name_edit = FittedText(self)
        self.path_edit = FittedText(self, path=True)
        self.log_edit = FittedText(self)

    def make_label(self):
        label = QLabel(self)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet('background:#ffe0a9; color:#903a18; border:1px solid #657d85; border-radius:4px; font:bold 12px "' + UI_FONT + '";')
        return label

    def layout_controls(self, compact):
        self.compact = compact
        self.setFixedSize(360 if compact else 598, 114 if compact else 228)
        dx, dy = (-227,-23) if compact else (0,0)
        for i,style in enumerate(STYLES):
            self.buttons[style].move(26 + (i%2)*105,32+(i//2)*35)
            self.buttons[style].setVisible(not compact)
        for key,x,y in [('vol_down',233,67),('vol_up',288,67),('previous',350,67),('play',433,67),('next',498,67),('show',233,103),('hide',288,103),('seq',350,103),('restore',433,103),('random',498,103)]:
            self.buttons[key].move(x+dx,y+dy)
        for key,x,y in [('delete',233,138),('delete_previous',288,138),('open',233,172),('exit',548,171)]:
            self.buttons[key].move(x,y)
            self.buttons[key].setVisible(not compact)
        for widget,x,y,w in [(self.time_label,233,31,55),(self.total_label,288,31,55),(self.count_label,519,31,58),(self.name_edit,350,31,164)]:
            widget.setGeometry(x+dx,y+dy,w,29)
        self.path_edit.setGeometry(288,172,260,29)
        self.log_edit.setGeometry(350,138,227,29)
        self.path_edit.setVisible(not compact)
        self.log_edit.setVisible(not compact)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor('#00b7ed'))
        painter.setPen(QPen(QColor('#657d85'),1))
        rect = QRectF(0.5,0.5,359,113) if self.compact else QRectF(15,22,572,192)
        painter.drawRoundedRect(rect,12,12)

    def mousePressEvent(self,event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self,event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self.drag_offset)

    def mouseReleaseEvent(self,event):
        self.drag_offset = None

    def log(self, message, detail=None):
        self.log_edit.show_text(message)
        if detail:
            self.log_edit.setToolTip(message + '\n' + detail)
        self.setToolTip(message if not detail else message + '\n' + detail)

    def startup(self):
        root = self.library.get('root')
        if root and Path(root).is_dir():
            self.open_folder(root)
        else:
            self.choose_folder()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self,'Select music folder',str(self.library.root or Path.home()))
        if folder:
            self.open_folder(folder)
        elif not self.library.root:
            self.log('Use OPEN to select a folder')

    def open_folder(self, folder):
        self.stop_audio()
        self.current = None
        self.failed.clear()
        self.back_stack = []
        try:
            saved = self.library.open(folder)
            self.path_edit.show_text(str(self.library.root))
            self.log(f'Loaded {len(self.library.tracks)} tracks')
            target = saved if saved in self.library.tracks else self.library.next(None,self.mode=='RANDOM')
            self.play_track(target)
        except Exception as exc:
            self.log('Open failed',str(exc))
        self.update_labels()

    def stop_audio(self):
        if self.audio_ready:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        if self.audio_stream is not None:
            self.audio_stream.close()
            self.audio_stream = None
        self.playing = False
        self.paused = False
        self.set_play_icon()

    def play_track(self, path, record_navigation=True):
        if record_navigation and self.current and self.current != path:
            self.back_stack.append(self.current)
        self.stop_audio()
        self.current = path
        self.classified_path = None
        self.successors = []
        self.elapsed = 0
        self.duration = 0
        if not path:
            self.name_edit.show_text('')
            self.log('No tracks available')
            self.update_labels()
            return
        self.name_edit.show_text(Path(path).name)
        if not self.audio_ready:
            self.log('Audio unavailable')
            self.update_labels()
            return
        try:
            # Decode from a private disk-backed snapshot, keeping the source
            # unlocked on Windows so classification never interrupts playback.
            self.audio_stream = tempfile.TemporaryFile(mode='w+b')
            with open(path, 'rb') as source:
                shutil.copyfileobj(source, self.audio_stream)
            self.audio_stream.seek(0)
            pygame.mixer.music.load(self.audio_stream, Path(path).suffix.lstrip('.'))
            pygame.mixer.music.set_volume(self.volume / 100)
            pygame.mixer.music.play()
            self.started_at = time.monotonic()
            self.playing = True
            self.library.played(path)
            try:
                meta = AudioMetadata(path)
                self.duration = float(meta.info.length) if meta else 0
            except Exception:
                pass
            self.failed.discard(path)
        except Exception as exc:
            self.stop_audio()
            self.failed.add(path)
            self.log('Cannot play; skipped',str(exc))
            if any(p not in self.failed for p in self.library.tracks):
                QTimer.singleShot(0,self.next_track)
            else:
                self.log('No playable tracks',str(exc))
        self.set_play_icon()
        self.update_labels()

    def next_track(self):
        if not self.library.root:
            self.log('Use OPEN to select a folder')
            return
        target = None
        if self.classified_path and self.mode == 'SEQ':
            target = next((p for p in self.successors if p in self.library.tracks), None)
        if target is None:
            target = self.library.next(self.current,self.mode=='RANDOM')
        for _ in range(len(self.library.tracks)):
            if target not in self.failed:
                break
            target = self.library.next(target,self.mode=='RANDOM')
        if target in self.failed:
            self.log('No playable tracks')
            return
        self.play_track(target)

    def previous(self):
        if not self.library.tracks:
            return
        if self.mode == 'RANDOM':
            target = None
            while self.back_stack:
                candidate = self.back_stack.pop()
                if candidate in self.library.tracks and candidate != self.current:
                    target = candidate
                    break
            if target is None:
                self.log('No previous track')
                return
        else:
            index = self.library.tracks.index(self.current) if self.current in self.library.tracks else 0
            target = self.library.tracks[(index-1)%len(self.library.tracks)]
        self.play_track(target, record_navigation=False)

    def toggle_play(self):
        if not self.audio_ready:
            self.log('Audio unavailable')
            return
        if self.paused:
            pygame.mixer.music.unpause()
            self.started_at = time.monotonic()
            self.paused = False
            self.playing = True
        elif self.playing:
            self.elapsed += time.monotonic() - self.started_at
            pygame.mixer.music.pause()
            self.paused = True
            self.playing = False
        elif self.current:
            self.failed.discard(self.current)
            self.play_track(self.current)
        else:
            self.next_track()
        self.set_play_icon()

    def set_play_icon(self):
        self.buttons['play'].setIcon(QIcon(str(ICONS / ('Pause.png' if self.playing else 'Play.png'))))

    def change_volume(self, amount):
        self.volume = min(100,max(0,self.volume + amount))
        if self.audio_ready:
            pygame.mixer.music.set_volume(self.volume/100)
        self.library.set('volume',self.volume)
        self.log(f'Volume {self.volume}%')

    def set_mode(self, mode):
        self.mode = mode
        self.library.set('mode',mode)
        self.update_mode()
        self.log('Sequential mode' if mode=='SEQ' else 'Random mode')

    def update_mode(self):
        for key,name in [('seq','SEQ'),('random','RANDOM')]:
            button = self.buttons[key]
            button.setCheckable(True)
            button.setChecked(self.mode == name)
            icon = name + ('_ACTIVE' if self.mode==name else '') + '.png'
            button.setIcon(QIcon(str(ICONS/icon)))

    def mutate_current(self):
        if not self.current or self.current not in self.library.tracks:
            self.log('Current track unavailable')
            return
        old = self.current
        index = self.library.tracks.index(old)
        was_paused = self.paused
        self.stop_audio()  # Release Windows file handle before moving the song.
        try:
            self.library.delete(old)
            message = 'Deleted'
        except Exception as exc:
            if Path(old).exists():
                self.play_track(old)
                if was_paused:
                    self.toggle_play()
            else:
                self.library.scan()
                self.next_track()
            self.log('Operation failed',str(exc))
            return
        target = self.library.next(old,True) if self.mode=='RANDOM' else (self.library.tracks[index % len(self.library.tracks)] if self.library.tracks else None)
        self.play_track(target)
        self.log(message)

    def classify(self, style):
        if self.classified_path:
            self.log('Track already classified')
            return
        if not self.current or self.current not in self.library.tracks:
            self.log('Current track unavailable')
            return
        index = self.library.tracks.index(self.current)
        successors = self.library.tracks[index+1:] + self.library.tracks[:index]
        try:
            destination = self.library.classify(self.current, style)
        except Exception as exc:
            self.log('Move failed', str(exc))
            return
        self.classified_path = str(destination)
        self.successors = successors
        self.name_edit.setToolTip(str(destination))
        self.log('Moved: ' + style)
        self.update_labels()

    def delete_current(self):
        self.mutate_current()

    def delete_previous(self):
        if not self.current or len(self.library.history)<2:
            self.log('Previous track unavailable')
            return
        item = self.library.history[-2]
        if item['status']=='classified':
            self.log('Already classified; cannot delete')
            return
        path = item['path']
        if item['status']!='available' or path==self.current or path not in self.library.tracks or not Path(path).is_file():
            self.log('Previous track unavailable')
            return
        try:
            self.library.delete(path)
            self.log('Previous track deleted')
            self.update_labels()
        except Exception as exc:
            self.log('Delete failed',str(exc))

    def restore(self):
        if not self.library.root:
            self.log('Use OPEN to select a folder')
            return
        try:
            path = self.library.restore()
            self.log('Restored' if path else 'Nothing to restore')
            if path:
                self.failed.discard(str(path))
            self.update_labels()
        except Exception as exc:
            self.log('Restore failed',str(exc))

    @staticmethod
    def time_text(seconds):
        seconds = max(0,int(seconds))
        return f'{seconds//60:02d}:{seconds%60:02d}'

    def update_labels(self):
        elapsed = self.elapsed + (time.monotonic()-self.started_at if self.playing else 0)
        self.time_label.setText(self.time_text(elapsed))
        self.total_label.setText(self.time_text(self.duration))
        index = self.library.tracks.index(self.current)+1 if self.current in self.library.tracks else 0
        self.count_label.setText(f'{index}/{len(self.library.tracks)}')

    def tick(self):
        self.update_labels()
        if self.audio_ready and self.playing and not pygame.mixer.music.get_busy():
            self.next_track()

    def closeEvent(self,event):
        self.timer.stop()
        self.stop_audio()
        self.library.close()
        if self.audio_ready:
            pygame.mixer.quit()
        event.accept()


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    app.setFont(QFont(UI_FONT,9))
    player = Player()
    player.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
