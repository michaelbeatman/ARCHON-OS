import os
import time
import shutil

WORKSPACE_DIR = r".\agent_workspace"
DAYS = 7
SECONDS_IN_DAY = 86400
current_time = time.time()
deleted_files = 0
deleted_dirs = 0

print(f"Starte rekursive Garbage Collection fr {WORKSPACE_DIR}")

if os.path.exists(WORKSPACE_DIR):
    for root, dirs, files in os.walk(WORKSPACE_DIR, topdown=False):
        for filename in files:
            if filename == ".gitkeep": continue
            filepath = os.path.join(root, filename)
            if (current_time - os.path.getmtime(filepath)) > (DAYS * SECONDS_IN_DAY):
                try:
                    os.remove(filepath)
                    deleted_files += 1
                except: pass
                
        # Lsche leere Ordner, nachdem die Dateien drinnen gelscht wurden
        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            if not os.listdir(dirpath): # Wenn leer
                try:
                    os.rmdir(dirpath)
                    deleted_dirs += 1
                except: pass

print(f"Garbage Collection abgeschlossen: {deleted_files} alte Scratchpads und {deleted_dirs} leere Ordner gelscht.")
