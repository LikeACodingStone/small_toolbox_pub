import os,sys, ctypes
import re, time
import threading
import configparser
import random
from datetime import datetime

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QMessageBox, QButtonGroup
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtCore import pyqtSignal, QObject
import pygame
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from BaseModules import ConfigParseHandle, GetCurrentFolder, MainWindow, ConfigModuleHandle
from AudioPlayer import AudioPlayer, Communicator
from Ui_RandomPlayWeight import Ui_MainWindow

def GetMediaByIndex(playList, mediaIndex):
    filePath = playList[mediaIndex]
    mediName = filePath.split("\\")[-1]
    return mediName

def player_thread(player):
    player.run()

global g_playList
global g_mediaIndex
global g_folderIndex
global g_audio_player
global g_config_parse
global g_config_mode

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
def SlotDelete():
    GenerateDeletFiles()

@pyqtSlot()
def SlotNextSong():
    global g_audio_player
    global g_playList
    global g_config_mode

    # ✅ 防止空列表
    if not g_playList:
        return

    # ✅ 混合隨機種子（時間 + 線程 + 進程）
    seed_val = time.time() + threading.get_ident() + os.getpid()
    random.seed(seed_val)

    max_index = len(g_playList) - 1

    if g_config_mode.getRandomMode():
        # ✅ 避免隨機到同一首
        current = g_audio_player.current_index
        new_index = current

        if len(g_playList) > 1:
            while new_index == current:
                new_index = random.randint(0, max_index)

        g_audio_player.current_index = new_index

    else:
        # ✅ 順序播放 + 防越界（循環）
        g_audio_player.current_index += 1
        if g_audio_player.current_index > max_index:
            g_audio_player.current_index = 0

    # ✅ 播放
    g_audio_player.play_audio()

    # ✅ 更新UI顯示歌曲名稱
    ui.lineEdit.setText(GetMediaByIndex(g_playList, g_audio_player.current_index))

# ✅✅✅ 【统一 UI 刷新入口】
@pyqtSlot(int, str)
def OnTrackChanged(index, filename):
    ui.lineEdit.setText(filename)

@pyqtSlot()
def SlotBtnExit():
    g_audio_player.is_quit = True
    QApplication.quit()
    sys.exit(0)

@pyqtSlot()
def SlotHandleNext():
    ui.lineEdit.setText(GetMediaByIndex(g_playList ,g_audio_player.current_index))

def GenerateDeletFiles():
    global g_audio_player
    global g_playList
    global g_config_parse
    fileNameContent = g_playList[g_audio_player.current_index]
    g_config_parse.AddDeleteFileList(fileNameContent)

def GetIniList():
    global g_config_parse
    playList = []
    for root, dirs, files in os.walk(g_config_parse._media_root_val):
        for file in files:
            if not file.endswith(".wma"):
                play_file = root + os.sep + file
                playList.append(play_file)
    return playList

if __name__ == '__main__':
    if sys.platform == "win32":
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    CONFIG = "config_random.ini"
    g_config_parse = ConfigParseHandle(CONFIG)
    CONFIG_MODE = "config_modules.ini"
    g_config_mode = ConfigModuleHandle(CONFIG_MODE)
    app = QtWidgets.QApplication(sys.argv)
    MainWindow = MainWindow(307,95)
    ui = Ui_MainWindow()
    ui.setupUi(MainWindow)
    g_playList = []
    g_mediaIndex = 1
    g_playList = GetIniList()
    communicator = Communicator()
    g_audio_player = AudioPlayer(g_playList, g_mediaIndex, communicator, g_config_mode.getRandomMode())
    ui.lineEdit.setText(GetMediaByIndex(g_playList, g_mediaIndex))
    ui.btnNext.clicked.connect(SlotNextSong)
    ui.btnPlay.clicked.connect(SlotPlay)
    ui.btnPause.clicked.connect(SlotPause)
    ui.btnDel.clicked.connect(SlotDelete)
    ui.btnExit.clicked.connect(SlotBtnExit)
    g_audio_player.signal_trackChanged.connect(OnTrackChanged)
    if g_config_mode.getPlayOnlyMode():
        ui.btnDel.hide()
    MainWindow.show()
    sys.exit(app.exec_())