#!/usr/bin/env bash
# Ubuntu/Debian prerequisites. Run explicitly; packaging never invokes sudo.
set -euo pipefail
# Accept the short form (English01) or the full branch name (English01_AudioInsertChTTS).
tool="${1:-}"
tool="${tool%%_*}"
case "$tool" in
    English01) packages=(ffmpeg curl) ;;
    English02) packages=(calibre python3-tk) ;;
    English03) packages=(calibre poppler-utils tesseract-ocr tesseract-ocr-eng zip unzip curl) ;;
    Audio04) packages=(libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libasound2t64) ;;
    Audio01|Audio03|Video01) packages=(libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1) ;;
    Audio02) packages=(ffmpeg libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1) ;;
    all) packages=(ffmpeg curl calibre python3-tk poppler-utils tesseract-ocr tesseract-ocr-eng zip unzip libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libasound2t64) ;;
    *) echo 'Usage: bash Envsetup/setup_system.sh {English01|English02|English03|Audio01|Audio02|Audio03|Audio04|Video01|all}' >&2; exit 2 ;;
esac
sudo apt-get update
sudo apt-get install -y build-essential python3-dev python3-venv "${packages[@]}"
if [[ "$tool" == English01 || "$tool" == English03 || "$tool" == all ]]; then
    if ! command -v ollama >/dev/null; then
        echo 'Install Ollama from https://ollama.com/download, then rerun setup_tools.sh.' >&2
        exit 1
    fi
fi
