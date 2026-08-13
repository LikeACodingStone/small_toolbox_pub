#!/usr/bin/env bash
# =============================================================================
# SetupCPU.sh - Book vocabulary insertion CPU environment deployment script
# Usage: bash EnvSetup/SetupCPU.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "${CYAN}$*${NC}"; }

ENVSETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_DIR="$(dirname "$ENVSETUP_DIR")"
VENV_DIR="$CODE_DIR/venv"
REQUIREMENTS="$ENVSETUP_DIR/requirements.txt"
PIP_PACKAGES="$ENVSETUP_DIR/pip_packages"
BASHRC="$HOME/.bashrc"
OLLAMA_MODEL="qwen2.5:7b"
CPU_THREADS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"

remove_bashrc_block() {
    local marker="$1"
    local marker_end="$2"
    [[ -f "$BASHRC" ]] || return 0
    python3 - "$BASHRC" "$marker" "$marker_end" << 'PYEOF'
import sys
from pathlib import Path

path = Path(sys.argv[1])
marker = sys.argv[2]
marker_end = sys.argv[3]
text = path.read_text(encoding="utf-8", errors="ignore")
start = text.find(marker)
while start != -1:
    end = text.find(marker_end, start)
    if end == -1:
        break
    end += len(marker_end)
    if end < len(text) and text[end:end + 1] == "\n":
        end += 1
    text = text[:start].rstrip() + "\n" + text[end:].lstrip()
    start = text.find(marker)
path.write_text(text, encoding="utf-8")
PYEOF
}

echo ""
section "========== 0. System Information =========="
info "Hostname     : $(hostname)"
info "OS           : $(lsb_release -sd 2>/dev/null || grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '"')"
info "Kernel       : $(uname -r)"
info "Python       : $(python3 --version 2>&1)"
info "CPU threads  : $CPU_THREADS"
info "ENVSETUP_DIR : $ENVSETUP_DIR"
info "CODE_DIR     : $CODE_DIR"

section "========== 1. Checking required files =========="
[[ -f "$REQUIREMENTS" ]] || die "Not found: $REQUIREMENTS"
[[ -d "$PIP_PACKAGES" ]] || warn "Offline pip package directory not found: $PIP_PACKAGES"
success "Required setup files checked"

section "========== 2. Installing system dependencies =========="
sudo apt-get update -qq
sudo apt-get install -y \
    python3-venv \
    python3-pip \
    curl \
    calibre \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    zip \
    unzip
success "System dependencies installed"

section "========== 3. Installing Ollama =========="
if command -v ollama &>/dev/null; then
    success "Ollama already installed: $(ollama --version 2>&1)"
else
    info "Downloading and installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    success "Ollama installed"
fi

if ! pgrep -x "ollama" &>/dev/null; then
    info "Starting Ollama service..."
    ollama serve &>/dev/null &
    for i in {1..15}; do
        if curl -s http://localhost:11434 &>/dev/null; then
            success "Ollama service is up"
            break
        fi
        info "Waiting for Ollama to start... ($i/15)"
        sleep 2
    done
else
    success "Ollama service already running"
fi

if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
    success "Model $OLLAMA_MODEL already present"
else
    info "Pulling model $OLLAMA_MODEL (this may take a while)..."
    ollama pull "$OLLAMA_MODEL"
    success "Model $OLLAMA_MODEL pulled"
fi

section "========== 4. Creating Python venv =========="
if [[ -d "$VENV_DIR" ]]; then
    warn "venv already exists, skipping creation: $VENV_DIR"
else
    python3 -m venv "$VENV_DIR"
    success "venv created: $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
success "venv activated: $(python3 --version)"

section "========== 5. Installing Python dependencies =========="
pip install --upgrade pip --quiet

if [[ -d "$PIP_PACKAGES" ]] && pip install \
    --no-index \
    --find-links="$PIP_PACKAGES" \
    -r "$REQUIREMENTS" \
    --quiet; then
    success "Offline installation complete"
else
    warn "Offline install incomplete, falling back to online..."
    if [[ -d "$PIP_PACKAGES" ]]; then
        pip install \
            --find-links="$PIP_PACKAGES" \
            -r "$REQUIREMENTS" \
            --quiet
    else
        pip install \
            -r "$REQUIREMENTS" \
            --quiet
    fi
    success "Hybrid installation complete"
fi

section "========== 5b. Installing optional Python enhancements =========="
for optional_package in pronouncing eng-to-ipa spacy; do
    if pip install "$optional_package" --quiet; then
        success "Optional package installed: $optional_package"
    else
        warn "Optional package failed: $optional_package"
    fi
done

section "========== 5c. Installing optional spaCy model =========="
if python3 - << 'PYEOF'
import spacy
spacy.load("en_core_web_sm")
PYEOF
then
    success "spaCy model en_core_web_sm already available"
else
    warn "spaCy model en_core_web_sm missing; trying online download"
    if python3 -m spacy download en_core_web_sm; then
        success "spaCy model en_core_web_sm installed"
    else
        warn "spaCy model download failed. Proper noun filtering will fall back to filter.txt and config SkipWords."
    fi
fi

section "========== 6. Writing CPU environment variables =========="
MARKER="# >>> bookvocab-cpu-env >>>"
MARKER_END="# <<< bookvocab-cpu-env <<<"
GPU_MARKER="# >>> bookvocab-gpu-env >>>"
GPU_MARKER_END="# <<< bookvocab-gpu-env <<<"

remove_bashrc_block "$MARKER" "$MARKER_END"
remove_bashrc_block "$GPU_MARKER" "$GPU_MARKER_END"

cat >> "$BASHRC" << EOF

$MARKER
export BOOKVOCAB_DEVICE=cpu
export BOOKVOCAB_CPU_THREADS=$CPU_THREADS
export BOOKVOCAB_MAX_WORKERS=$CPU_THREADS
export BOOKVOCAB_OLLAMA_MODEL=$OLLAMA_MODEL
$MARKER_END
EOF
success "CPU environment variables written to $BASHRC"

export BOOKVOCAB_DEVICE=cpu
export BOOKVOCAB_CPU_THREADS="$CPU_THREADS"
export BOOKVOCAB_MAX_WORKERS="$CPU_THREADS"
export BOOKVOCAB_OLLAMA_MODEL="$OLLAMA_MODEL"

python3 - "$CODE_DIR/config.ini" << 'PYEOF'
import configparser
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
parser = configparser.ConfigParser()
parser.optionxform = str
parser.read(config_path, encoding="utf-8")
if not parser.has_section("RuntimeConfig"):
    parser.add_section("RuntimeConfig")
parser.set("RuntimeConfig", "CaculateCore", "CPU")
parser.set("RuntimeConfig", "MaxWorkers", "0")
parser.set("RuntimeConfig", "BookWorkers", "1")
parser.set("RuntimeConfig", "OcrWorkers", "0")
if not parser.has_section("TranslationConfig"):
    parser.add_section("TranslationConfig")
parser.set("TranslationConfig", "TranslationBatchSize", "8")
parser.set("TranslationConfig", "MaxContextChars", "1800")
parser.set("TranslationConfig", "OllamaTimeoutSeconds", "240")
parser.set("TranslationConfig", "OllamaRequestRetries", "2")
parser.set("TranslationConfig", "OllamaRetrySleepSeconds", "3")
with config_path.open("w", encoding="utf-8") as handle:
    parser.write(handle)
PYEOF
success "config.ini CPU worker and Ollama timeout defaults updated"

section "========== 7. Verification =========="
info "--- Python packages ---"
pip show requests | grep -E "Name|Version"
pip show cefrpy   | grep -E "Name|Version"
pip show wordfreq | grep -E "Name|Version"
pip show pronouncing 2>/dev/null | grep -E "Name|Version" || warn "pronouncing not installed"
pip show eng-to-ipa 2>/dev/null | grep -E "Name|Version" || warn "eng-to-ipa not installed"
pip show spacy 2>/dev/null | grep -E "Name|Version" || warn "spacy not installed"

info "--- Book conversion tools ---"
ebook-convert --version 2>&1 | head -1 || warn "ebook-convert not found"
pdftotext -v 2>&1 | head -1 || warn "pdftotext not found"
tesseract --version 2>&1 | head -1 || warn "tesseract not found"

info "--- Ollama ---"
if curl -s http://localhost:11434/api/generate \
    -d "{\"model\":\"$OLLAMA_MODEL\",\"prompt\":\"hi\",\"stream\":false}" \
    --max-time 15 | grep -q "response"; then
    success "Ollama $OLLAMA_MODEL responding"
else
    warn "Ollama not responding - you may need to run 'ollama serve' manually"
fi

info "--- Project import ---"
PYTHONPATH="$CODE_DIR" python3 - << 'PYEOF'
from book_vocab_module import VocabularyAnnotator
annotator = VocabularyAnnotator()
print("VocabularyAnnotator OK")
PYEOF

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  CPU deployment complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "To run:"
echo "  cd $CODE_DIR"
echo "  bash run.sh"
echo ""
