import shutil, os

src_dir = 'C:\\.Antigravity-projekte\\AgenticOS-2026'
targets = [
    'C:\\.Antigravity-projekte\\ARCHON OS-Dist 0.1',
    'C:\\.Antigravity-projekte\\ARCHON OS-Dist 0.1 ink. knoledgeDB'
]
dirs_to_copy = ['backend', 'static', 'scripts']
files_to_copy = ['main.py', 'local_memory_bridge.py', 'local_security_guard.py', 'jev_router.py', 'core_skills_engine.py', 'core_dispatcher.py', 'research_engine.py', 'watchdog_daemon.py', 'process_catalog.py', 'views_core.py']

for target in targets:
    if not os.path.exists(target): continue
    for d in dirs_to_copy:
        src_path = os.path.join(src_dir, d)
        dst_path = os.path.join(target, d)
        if os.path.exists(src_path):
            if os.path.exists(dst_path): shutil.rmtree(dst_path)
            shutil.copytree(src_path, dst_path)
    for f in files_to_copy:
        src_path = os.path.join(src_dir, f)
        dst_path = os.path.join(target, f)
        if os.path.exists(src_path):
            shutil.copy2(src_path, dst_path)
print('Update done')
