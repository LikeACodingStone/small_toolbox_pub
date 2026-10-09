#!/usr/bin/env bash
# Ubuntu/Debian prerequisites. Run explicitly; packaging never invokes sudo.
set -euo pipefail
case "${1:-}" in
    A001) packages=(ffmpeg curl) ;;
    A002) packages=(calibre python3-tk) ;;
    A003) packages=(calibre poppler-utils tesseract-ocr tesseract-ocr-eng zip unzip curl) ;;
    A004) packages=(libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libasound2t64) ;;
    all) packages=(ffmpeg curl calibre python3-tk poppler-utils tesseract-ocr tesseract-ocr-eng zip unzip libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libasound2t64) ;;
    *) echo 'Usage: bash Envsetup/setup_system.sh {A001|A002|A003|A004|all}' >&2; exit 2 ;;
esac
sudo apt-get update
sudo apt-get install -y build-essential python3-dev python3-venv "${packages[@]}"
if [[ "$1" == A001 || "$1" == A003 || "$1" == all ]]; then
    if ! command -v ollama >/dev/null; then
        echo 'Install Ollama from https://ollama.com/download, then rerun setup_tools.sh.' >&2
        exit 1
    fi
fi
