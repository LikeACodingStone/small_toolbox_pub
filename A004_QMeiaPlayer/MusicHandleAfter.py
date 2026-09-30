
import os
import numpy as np
from datetime import datetime
import shutil
from BaseModules import ConfigParseHandle, GetCurrentFolder

class AddDeleteBySdCard:
    def __init__(self):
        self.cfgHandle = ConfigParseHandle("config.ini")
        self.LOCAL_MEDIA_ROOT =  self.cfgHandle._media_root_val
        self.SD_CARD_FILE = self.cfgHandle._abs_config_folder + os.sep + "music.txt"

    def isEffective(self, lineList):
        index = 0
        bEffective = False
        for val in lineList:
            if val == "音乐":
                bEffective = True
                break
            index += 1
        return bEffective, index

    def GetSdCardList(self, music_path):
        print(music_path)
        subMusicList = []
        with open(music_path, "r", encoding='utf-8') as fp:
            allLines = fp.readlines()
            for line in allLines:
                lineList = line.strip().split("/")
                bEff, index = self.isEffective(lineList)
                if bEff and len(lineList) >= (index + 3):
                    sub_path = lineList[-1]
                    subMusicList.append(sub_path)
        return subMusicList
    
    def GetLocalMediaList(self, path):
        local_pair_list = []
        local_file_list = []
        for root, dirs, files in os.walk(self.LOCAL_MEDIA_ROOT):
            for file in files:
                pair_val = []
                abs_path = root + os.sep + file
                pair_val.append(file)
                pair_val.append(abs_path)
                local_pair_list.append(pair_val)
                local_file_list.append(file)
        return local_pair_list, local_file_list

    def RunAddToDeleteTXT(self):
        subMusicList = self.GetSdCardList(self.SD_CARD_FILE)
        localPairList, localFileList = self.GetLocalMediaList(self.LOCAL_MEDIA_ROOT)
        diffListInLocal = np.setdiff1d(localFileList, subMusicList) # in local file but not in sd card file
        diffAbsPath = [value for key, value in localPairList if key in diffListInLocal]
        for fileName in diffAbsPath:
            self.cfgHandle.AddDeleteFileList(fileName)
            print(fileName)

    def ClearDeleteTxtAndDeleteFiles(self):
        txt_path = self.cfgHandle._abs_config_folder + os.sep + self.cfgHandle._delete
        if not os.path.exists(txt_path):
            return 
        with open(txt_path, "r", encoding='utf-8', errors='ignore') as fp:
            allLines = fp.readlines()
            for line in allLines:
                lineVal = line.strip()
                print(lineVal)
                if len(lineVal) > 5:
                    os.remove(lineVal)
             
        
        current_time = datetime.now()
        str_file_date =  str(current_time.year) +  "_" + str(current_time.month) +  "_" + \
                        str(current_time.day) +  "_" + str(current_time.hour) +  "_" + str(current_time.minute)
        backBackFiles = GetCurrentFolder() + os.sep + "backupFiles" + os.sep + str_file_date + ".txt"
        os.rename(txt_path, backBackFiles)
      
    def ClassificationStyles(self):
        bluesDict = {self.cfgHandle._abs_config_folder + os.sep + self.cfgHandle.style_blues + ".txt":
                     self.cfgHandle.getStyleFolder("blues")}
        hardRockDict = {self.cfgHandle._abs_config_folder + os.sep + self.cfgHandle.style_hardRock + ".txt":
                        self.cfgHandle.getStyleFolder("hard")}
        metalDict = {self.cfgHandle._abs_config_folder + os.sep + self.cfgHandle.style_metal + ".txt":
                     self.cfgHandle.getStyleFolder("metal")}
        popDict = {self.cfgHandle._abs_config_folder + os.sep + self.cfgHandle.style_popular + ".txt":
                    self.cfgHandle.getStyleFolder("pop")}
        punkDict = {self.cfgHandle._abs_config_folder + os.sep + self.cfgHandle.style_punk + ".txt":
                    self.cfgHandle.getStyleFolder("punk")}
        countryDict = {self.cfgHandle._abs_config_folder + os.sep + self.cfgHandle.style_country + ".txt":
                    self.cfgHandle.getStyleFolder("country")}
        soloDict = {self.cfgHandle._abs_config_folder + os.sep + self.cfgHandle.style_solo + ".txt":
                    self.cfgHandle.getStyleFolder("solo")}
        japaneseDict = {self.cfgHandle._abs_config_folder + os.sep + self.cfgHandle.style_japan + ".txt":
                    self.cfgHandle.getStyleFolder("japanese")}

        dictList = []
        dictList.append(bluesDict)
        dictList.append(hardRockDict)
        dictList.append(metalDict)
        dictList.append(popDict)
        dictList.append(punkDict)
        dictList.append(countryDict)
        dictList.append(soloDict)
        dictList.append(japaneseDict)
        
        for dict in dictList:
            for key, val in dict.items():
                if not os.path.exists(key):
                    continue
                with open(key, "r+", encoding='utf-8', errors='ignore') as fp:
                    readlines  = fp.readlines()
                    for line in readlines:
                        line = line.strip()
                        lineName = line.split("\\")[-1]
                        newPath = val + os.sep + lineName
                        if os.path.exists(line):
                            shutil.move(line, newPath)
                            print(line, newPath)
                    fp.seek(0)
                    fp.truncate(0)
                    fp.close()


addDelete = AddDeleteBySdCard()

#addDelete.RunAddToDeleteTXT()

addDelete.ClearDeleteTxtAndDeleteFiles()
addDelete.ClassificationStyles()

