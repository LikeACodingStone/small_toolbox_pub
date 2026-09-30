import os

id = 1
if id == 0:
    current_file_path = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file_path)
    music_path = current_dir + os.sep + "音乐"
    listFiles = []
    for root, dirs, files in os.walk(music_path):
        for file in files:
            absPath = root + os.sep + file
            print(absPath)

if id == 1:
    current_file_path = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file_path)
    music_path = current_dir + os.sep + "MP3Files"
    listFiles = []
    for root, dirs, files in os.walk(music_path):
        for file in files:
            absPath = root + os.sep + file
            print(absPath)
# this is walk for sd card music.txt running on ubuntu 
# python3 WalkFiles.py >> ~/zhouWork/music.txt

