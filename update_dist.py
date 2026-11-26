import shutil, os

src_dir = r'.'
_env_targets = [t.strip() for t in os.environ.get("ARCHON_DIST_TARGETS", "").split(os.pathsep) if t.strip()]
targets = _env_targets
dirs_to_copy = ['archon', 'backend', 'static', 'scripts', 'config', 'docs']
files_to_copy = [
    'main.py',
    'docker-compose.yml',
    'local_memory_bridge.py',
    'local_security_guard.py',
    'jev_router.py',
    'core_skills_engine.py',
    'core_dispatcher.py',
    'research_engine.py',
    'watchdog_daemon.py',
    'process_catalog.py',
    'views_core.py',
    'dossier_builder.py',
    'telegram_notify.py',
    'agent_profiles.json',
    'roles.json'
]

for target in targets:
    if not os.path.exists(target):
        print(f"Target does not exist: {target}")
        continue
    print(f"Updating target: {target}")
    for d in dirs_to_copy:
        src_path = os.path.join(src_dir, d)
        dst_path = os.path.join(target, d)
        if os.path.exists(src_path):
            shutil.copytree(
                src_path,
                dst_path,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.log', '.git')
            )
    for f in files_to_copy:
        src_path = os.path.join(src_dir, f)
        dst_path = os.path.join(target, f)
        if os.path.exists(src_path):
            shutil.copy2(src_path, dst_path)

print('Update done successfully.')

