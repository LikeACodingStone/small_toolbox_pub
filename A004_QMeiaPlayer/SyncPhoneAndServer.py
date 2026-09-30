'''
1. 幫我生成一段python代碼，完成以下的功能，代碼運行在windows系統上
2. 在代碼裏面可以手動支持配置兩個路徑，一個是手機的音樂文件夾根目錄，一個是服務器的音樂文件根目錄
3. 手機可能是要基於adb root的權限訪問，服務器可能是本地磁盤，也可能是遠程的samba服務，都要支持。
3. 對這個兩個根目錄裏面的内容進行同步，首先要求是一樣的子文件夾才能進行同步，如果是只有服務器或者只有手機存在的子文件夾，則跳過同步
4. 同步規則就是對各個子文件裏面的文件進行比較，如果某個文件在其中一個存在，在另一個不存在，則刪除這個文件。
5. 把刪除的名字和路徑記錄下來寫在當前logs文件夾下面的log日志裏面，log文件用時間戳生成。 

PHONE_ROOT = "/storage/C527-1BFB/Music"
SERVER_ROOT = r"\\172.30.2.199\prv\MP3Files"

'''

import os
import subprocess
import datetime
import re
import unicodedata

# =========================
# CONFIG
# =========================

PHONE_ROOT = "/storage/C527-1BFB/Music"
SERVER_ROOT = r"\\172.30.2.199\prv\MP3Files"

ADB_PATH = "adb"

VALID_EXT = (".mp3", ".flac")

# 🛑 安全模式（先用 True 測試）
DRY_RUN = False


# =========================
# LOGGER
# =========================

def init_logger():
    os.makedirs("logs", exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"logs/sync_delete_{ts}.log"


def log_write(logfile, msg):
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg)


# =========================
# NAME NORMALIZATION（核心）
# =========================

def normalize_name(name):
    # Unicode 正規化（處理奇怪符號）
    name = unicodedata.normalize("NFKD", name)

    # 小寫
    name = name.lower()

    # 去掉擴展名
    name = os.path.splitext(name)[0]

    # 只保留字母 + 數字
    name = re.sub(r'[^a-z0-9]', '', name)

    return name


# =========================
# ADB
# =========================

def adb_shell(cmd):
    result = subprocess.check_output(
        [ADB_PATH, "shell", cmd],
        stderr=subprocess.DEVNULL
    )
    return result.decode(errors="ignore").strip()


def adb_delete(path):
    if DRY_RUN:
        return

    subprocess.run(
        [ADB_PATH, "shell", "rm", "-f", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


# =========================
# PHONE FILES
# =========================

def phone_dirs(root):
    result = adb_shell(f'find "{root}" -mindepth 1 -maxdepth 1 -type d')

    if not result:
        return []

    return [os.path.basename(x.strip()) for x in result.split("\n") if x.strip()]


def phone_music_files(folder):
    result = adb_shell(f'find "{folder}" -mindepth 1 -maxdepth 1 -type f')

    files = {}

    if not result:
        return files

    for f in result.split("\n"):
        f = f.strip()
        if not f:
            continue

        name = os.path.basename(f)

        if name.lower().endswith(VALID_EXT):
            key = normalize_name(name)
            files[key] = name

    return files


# =========================
# SERVER FILES
# =========================

def server_dirs(root):
    if not os.path.exists(root):
        return []

    return [
        d for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d))
    ]


def server_music_files(folder):
    files = {}

    if not os.path.exists(folder):
        return files

    for f in os.listdir(folder):
        name = f.strip()

        if name.lower().endswith(VALID_EXT):
            key = normalize_name(name)
            files[key] = f

    return files


def server_delete(path):
    if DRY_RUN:
        return

    try:
        os.remove(path)
    except Exception:
        pass


# =========================
# SYNC
# =========================

def sync_folder(folder, logfile):
    phone_path = f"{PHONE_ROOT}/{folder}"
    server_path = os.path.join(SERVER_ROOT, folder)

    phone_files = phone_music_files(phone_path)
    server_files = server_music_files(server_path)

    phone_keys = set(phone_files.keys())
    server_keys = set(server_files.keys())

    # 📱 手機多 → 刪手機
    for k in phone_keys - server_keys:
        real_name = phone_files[k]
        full = f"{phone_path}/{real_name}"

        log_write(logfile, f"DELETE_PHONE {full}")

        adb_delete(full)

    # 💻 服務器多 → 刪服務器
    for k in server_keys - phone_keys:
        real_name = server_files[k]
        full = os.path.join(server_path, real_name)

        log_write(logfile, f"DELETE_SERVER {full}")

        server_delete(full)


# =========================
# MAIN
# =========================

def main():
    logfile = init_logger()

    print("Scanning phone folders...")
    p_dirs = set(phone_dirs(PHONE_ROOT))

    print("Scanning server folders...")
    s_dirs = set(server_dirs(SERVER_ROOT))

    # 只同步共同目錄
    common = p_dirs & s_dirs

    print("Folders to sync:", len(common))

    for d in sorted(common):
        print("Sync:", d)
        sync_folder(d, logfile)

    print("Done")


# =========================

if __name__ == "__main__":
    main()