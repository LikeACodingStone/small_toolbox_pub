import os, sys, ctypes
import re, time, threading, configparser
from datetime import datetime

import platform
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox
from PyQt5.QtCore import *

from Ui_PlayerWeight import Ui_FreePlayer
from BaseModules import ConfigParseHandle, GetCurrentFolder, MainWindow
from AudioPlayer import AudioPlayer, Communicator

# ========== 歌名工具 ==========
def GetMediaByIndex(playList, mediaIndex):
    if 0 <= mediaIndex < len(playList):
        filePath = playList[mediaIndex]
        # 使用 os.path.basename 自动处理 \ 或 /
        return os.path.basename(filePath) 
    return "No Media"

def player_thread(player):
    player.run()

global g_playList
global g_mediaIndex
global g_audio_player
global g_config_parse

# ================= 按钮槽函数 =================
@pyqtSlot()
def SlotPlay():
    global g_audio_player
    if g_audio_player.is_paused:
        g_audio_player.resume_audio()
    else:
        thread = threading.Thread(target=player_thread, args=(g_audio_player,))
        thread.start()

@pyqtSlot()
def SlotPause():
    global g_audio_player
    if g_audio_player.is_playing:
        g_audio_player.pause_audio()

@pyqtSlot()
def SlotNextSong():
    global g_audio_player
    g_audio_player.current_index += 1
    g_audio_player.play_audio()   # ✅ 自动刷新 UI

@pyqtSlot()
def SlotPreSong():
    global g_audio_player
    g_audio_player.current_index -= 1
    g_audio_player.play_audio()   # ✅ 自动刷新 UI

@pyqtSlot()
def SlotBtnExit():
    g_audio_player.is_quit = True
    QApplication.quit()
    sys.exit(0)

# 风格槽函数定义
@pyqtSlot()
def SlotBtnDel(): 
    current_file = g_playList[g_audio_player.current_index]
    g_config_parse.AddDeleteFileList(current_file)

@pyqtSlot()
def SlotBtnPop(): SaveToStyleFile("Popular.txt")
@pyqtSlot()
def SlotBtnBlues(): SaveToStyleFile("BluesJazz.txt")
@pyqtSlot()
def SlotBtnCountry(): SaveToStyleFile("Country.txt")
@pyqtSlot()
def SlotBtnMetal(): SaveToStyleFile("Metal.txt")
@pyqtSlot()
def SlotBtnPunk(): SaveToStyleFile("Punk.txt")
@pyqtSlot()
def SlotBtnHard(): SaveToStyleFile("HardRock.txt")
@pyqtSlot()
def SlotBtnSolo(): SaveToStyleFile("Solo.txt")
@pyqtSlot()
def SlotBtnJapan(): SaveToStyleFile("Japanese.txt")


def SaveToStyleFile(style_filename):
    """通用风格保存函数"""
    global g_audio_player, g_config_parse, g_playList
    if g_audio_player.current_index < len(g_playList):
        current_file = g_playList[g_audio_player.current_index]
        g_config_parse.AddStyleList(style_filename, current_file)

# ✅✅✅ 【统一 UI 刷新入口】
def OnTrackChanged(index, filename):
    ui.lineEdit.setText(filename)
    g_config_parse.setMediaIndex(index)

# ================= 读取配置 =================
def GetIniList():
    global g_config_parse
    playList = []
    # 确保路径在 Linux 下是标准化的
    target_dir = os.path.normpath(g_config_parse._media_folder_val)
    
    # 定义支持的音频格式
    valid_extensions = ('.mp3', '.flac', '.wav', '.ogg', '.m4a')
    
    if not os.path.exists(target_dir):
        print(f"错误：路径不存在 -> {target_dir}")
        return [], target_dir, 0

    for root, dirs, files in os.walk(target_dir):
        for file in files:
            # 1. 过滤掉隐藏文件 2. 匹配指定的音频后缀
            if not file.startswith('.') and file.lower().endswith(valid_extensions):
                # 使用 os.path.join 替代字符串拼接，确保跨平台兼容性
                play_file = os.path.join(root, file)
                playList.append(play_file)
    
    # 排序确保索引在不同系统间一致
    playList.sort()
    
    return playList, target_dir, int(g_config_parse._media_index_val)

# ================= 程序入口 =================
if __name__ == '__main__':
    if platform.system() == "Windows":
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

    CONFIG = "config.ini"
    g_config_parse = ConfigParseHandle(CONFIG)

    app = QtWidgets.QApplication(sys.argv)
    MainWindow = MainWindow(388, 85)
    ui = Ui_FreePlayer()
    ui.setupUi(MainWindow)

    # 绑定按钮
    ui.btnPlay.clicked.connect(SlotPlay)
    ui.btnPause.clicked.connect(SlotPause)
    ui.btnNext.clicked.connect(SlotNextSong)
    ui.btnPre.clicked.connect(SlotPreSong)
    ui.btnExit.clicked.connect(SlotBtnExit)
    ui.btnDel.clicked.connect(lambda: g_config_parse.AddDeleteFileList(g_playList[g_audio_player.current_index]))
    
    # 2. 绑定风格按钮 (利用 lambda 传入文件名)
    ui.btnPop.clicked.connect(lambda: g_config_parse.AddStyleList("Popular.txt", g_playList[g_audio_player.current_index]))
    ui.btnBlues.clicked.connect(lambda: g_config_parse.AddStyleList("BluesJazz.txt", g_playList[g_audio_player.current_index]))
    ui.btnCountry.clicked.connect(lambda: g_config_parse.AddStyleList("Country.txt", g_playList[g_audio_player.current_index]))
    ui.btnMetal.clicked.connect(lambda: g_config_parse.AddStyleList("Metal.txt", g_playList[g_audio_player.current_index]))
    ui.btnPunk.clicked.connect(lambda: g_config_parse.AddStyleList("Punk.txt", g_playList[g_audio_player.current_index]))
    ui.btnHard.clicked.connect(lambda: g_config_parse.AddStyleList("HardRock.txt", g_playList[g_audio_player.current_index]))
    ui.btnSolo.clicked.connect(lambda: g_config_parse.AddStyleList("Solo.txt", g_playList[g_audio_player.current_index]))
    ui.btnJapan.clicked.connect(lambda: g_config_parse.AddStyleList("Japanese.txt", g_playList[g_audio_player.current_index]))

    # 读取播放列表
    g_playList, g_folderIndex, g_mediaIndex = GetIniList()
    if not g_playList:
        print("错误：播放列表为空，请检查媒体路径！")
        sys.exit(1)

    # 确保索引不越界
    if g_mediaIndex < 0 or g_mediaIndex >= len(g_playList):
        g_mediaIndex = 0
        g_config_parse.setMediaIndex(0) # 重置配置文件中的索引

    communicator = Communicator()
    g_audio_player = AudioPlayer(g_playList, g_mediaIndex, communicator)

    # ✅✅✅ 绑定切歌信号 → 自动更新 UI
    g_audio_player.signal_trackChanged.connect(OnTrackChanged)

    # 初始化显示
    ui.lineEdit.setText(GetMediaByIndex(g_playList, g_mediaIndex))

    MainWindow.show()
    sys.exit(app.exec_())
