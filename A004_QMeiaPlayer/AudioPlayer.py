import pygame
import re, time, random, os
import platform

if platform.system() == "Windows":
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
else:
    # Linux 下不需要这些库，定义为空或跳过
    AudioUtilities = None
from mutagen import File
from mutagen.id3 import USLT, SYLT

from PyQt5.QtCore import pyqtSignal, QObject

# ================== 歌词通信（保持不动） ==================
class Communicator(QObject):
    update_signal = pyqtSignal(list, int)  # 歌词 + 页码

# ================== ✅ 播放器核心（最终修复版） ==================
class AudioPlayer(QObject):

    signal_playFinish = pyqtSignal(str)

    # ✅✅✅ 【核心】切歌专用信号：索引 + 文件名
    signal_trackChanged = pyqtSignal(int, str)

    def __init__(self, playlist, mediaIndex, communicator, isRandom=False):
        super().__init__()

        pygame.init()
        pygame.mixer.init()

        self.playlist = playlist
        self.current_index = mediaIndex
        self.listLength = len(self.playlist)

        self.is_paused = False
        self.is_playing = False
        self.is_quit = False

        self.end_event = pygame.USEREVENT + 1
        pygame.mixer.music.set_endevent(self.end_event)

        if platform.system() == "Windows" and AudioUtilities:
            try:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                system_volume = volume.GetMasterVolumeLevelScalar()
                pygame.mixer.music.set_volume(system_volume * 0.1)
            except Exception as e:
                print(f"Windows volume sync failed: {e}")
                pygame.mixer.music.set_volume(0.5)
        else:
            # Ubuntu/Linux 默认音量设置
            pygame.mixer.music.set_volume(0.5)

        self.communicator = communicator
        self._isRandom = isRandom

        # ✅ 歌词系统保持原样（不启用）
        # self.lyrics_window = LyricsWindow()
        # self.lyrics_window.show()
        # self.communicator.update_signal.connect(self.lyrics_window.update_lyrics)

        self.start_time = 0.0
        self.paused_time = 0.0
        self.pause_start = None

    # ✅✅✅ 【统一播放入口】
    def play_audio(self):

        # 防越界
        if self.current_index < 0:
            self.current_index = self.listLength - 1
        elif self.current_index >= self.listLength:
            self.current_index = 0

        file_path = self.playlist[self.current_index]

        if not file_path.endswith(".wma"):
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()

        self.is_playing = True
        self.is_paused = False

        self.start_time = time.time() * 1000
        self.paused_time = 0.0
        self.pause_start = None

        # ✅✅✅ 【关键修复：切歌立即同步 UI】
        self.signal_trackChanged.emit(
            self.current_index,
            os.path.basename(file_path)
        )

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == self.end_event:
                if self._isRandom:
                    self.current_index = random.randint(0, self.listLength - 1)
                else:
                    self.current_index += 1
                self.play_audio()

    def pause_audio(self):
        if not self.is_paused:
            pygame.mixer.music.pause()
            self.is_paused = True
            self.is_playing = False
            self.pause_start = time.time() * 1000

    def resume_audio(self):
        if self.is_paused:
            pygame.mixer.music.unpause()
            self.is_paused = False
            self.is_playing = True
            self.paused_time += time.time() * 1000 - self.pause_start
            self.pause_start = None

    def run(self):
        self.play_audio()
        while self.current_index < len(self.playlist):
            self.handle_events()
            time.sleep(0.05)
            if self.is_quit:
                break
        self.is_playing = False
