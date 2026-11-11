#!/bin/bash
# SHADOW SELF — one-time environment setup (no admin rights needed)
#   Makes a private Python environment in .venv/ inside this folder and installs
#   PyTorch + the AI agent's package into it, so everyone on the team has the same versions.
# Run from the shadow_self folder:   bash setup_env.sh
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "1/3  Creating .venv (private Python environment)..."
  python3 -m venv .venv
else
  echo "1/3  .venv already exists — reusing it"
fi

echo "2/3  Installing packages (PyTorch is ~100-200 MB, give it a few minutes)..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

echo "3/3  Checking..."
.venv/bin/python - <<'PY'
import sys, torch, openai
mps = torch.backends.mps.is_available() if hasattr(torch.backends, "mps") else False
print(f"     Python {sys.version.split()[0]} | PyTorch {torch.__version__} | openai {openai.__version__}")
print(f"     Apple GPU (MPS) available: {mps}  (not needed: this model trains fast on the CPU)")
x = torch.randn(64, 6); print(f"     Test calculation OK: {tuple((x @ torch.randn(6, 2)).shape)}")
PY

echo
echo "Done. Each time you open a new terminal, turn the environment on with:"
echo "    source .venv/bin/activate"
echo "Then run the usual commands, e.g.  python ml/train_shadow_net.py"
