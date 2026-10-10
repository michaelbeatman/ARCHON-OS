import os
import shutil
import glob

# Ordner anlegen
os.makedirs("archive/scratch_scripts", exist_ok=True)
os.makedirs("archive/screenshots", exist_ok=True)
os.makedirs("archive/legacy_backups", exist_ok=True)

# 1. Screenshots im Root archivieren
pngs = glob.glob("*.png")
for p in pngs:
    try:
        shutil.move(p, os.path.join("archive/screenshots", p))
    except Exception as e:
        print(f"Error moving {p}: {e}")

# 2. Build-Batch und Scratch-Skripte
scratch_patterns = ["build_batch*.py", "test_*.js", "inspect_*.js", "run_pw*.js", "scratch_*.js"]
for pattern in scratch_patterns:
    for f in glob.glob(pattern):
        try:
            shutil.move(f, os.path.join("archive/scratch_scripts", f))
        except Exception as e:
            print(f"Error moving {f}: {e}")

specific_scratch = ["find_views.py", "temp_check.js", "test_logs.txt", "test_output.html"]
for s in specific_scratch:
    if os.path.exists(s):
        try:
            shutil.move(s, os.path.join("archive/scratch_scripts", s))
        except Exception as e:
            print(f"Error moving {s}: {e}")

# 3. Alte .bak Backupdateien im Root archivieren
baks = glob.glob("*.bak*")
for b in baks:
    try:
        shutil.move(b, os.path.join("archive/legacy_backups", b))
    except Exception as e:
        print(f"Error moving {b}: {e}")

print("Bereinigung und Archivierung erfolgreich durchgeführt!")
