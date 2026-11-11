"""Puts the flat GitHub upload back into its real folders (UI/, config/, ...).
Run once from this folder:  python restore_folders.py   (Render runs it as the build command)."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "restore_map.json")) as f:
    mapping = json.load(f)
moved = 0
for flat, real in mapping.items():
    src, dst = os.path.join(HERE, flat), os.path.join(HERE, real)
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst) or HERE, exist_ok=True)
        os.replace(src, dst)
        moved += 1
print(f"Restored {moved} files into their folders.")
