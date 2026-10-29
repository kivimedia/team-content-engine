#!/bin/bash
# The laugh detector the automatic edit asks before it cuts a pause (29-Oct-2026, Connie:
# "dont cut out her laughs!"). Builds its own Python (torch on CPU + librosa), apart from
# the API's and the transcription worker's, and the upstream model at a pinned commit.
# Safe to run again: a finished step is skipped. Then set in .env:
#   TCE_PRODUCTION_LAUGH_PYTHON=$VENV/bin/python
#   TCE_PRODUCTION_LAUGH_DIR=$MODEL
# Unset (the default) = no laugh check: pauses are cut exactly as before.
set -euo pipefail

VENV=${TCE_LAUGH_VENV:-/home/ziv/.venvs/tce-laughs}
MODEL=${TCE_LAUGH_MODEL:-/home/ziv/tce-models/laughter-detection}
REPO=https://github.com/jrgillick/laughter-detection.git
COMMIT=5d5e0327916959d832d95ffbef5f484efc93d799

if [ ! -d "$MODEL/.git" ]; then
  mkdir -p "$(dirname "$MODEL")"
  git clone -q "$REPO" "$MODEL"
fi
git -C "$MODEL" fetch -q origin "$COMMIT" 2>/dev/null || true
git -C "$MODEL" checkout -q "$COMMIT"
test -s "$MODEL/checkpoints/in_use/resnet_with_augmentation/best.pth.tar"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
"$VENV/bin/pip" install -q librosa==1.0.0 numpy==2.5.4
"$VENV/bin/python" -c "import torch, librosa; print('laugh detector ready:', torch.__version__, librosa.__version__)"
echo "TCE_PRODUCTION_LAUGH_PYTHON=$VENV/bin/python"
echo "TCE_PRODUCTION_LAUGH_DIR=$MODEL"
