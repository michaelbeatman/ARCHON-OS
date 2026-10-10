import os

def patch_file(p):
    if not os.path.exists(p): return
    with open(p, 'r', encoding='utf-8') as f:
        c = f.read()

    # Remove the border from the pill and place it in the second line
    # Original: <div class="flex items-center gap-1.5 border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 rounded-md w-fit">
    old_pill = '<div class="flex items-center gap-1.5 border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 rounded-md w-fit">'
    new_pill = '<div class="flex items-center gap-1.5 w-fit">'
    
    if old_pill in c:
        c = c.replace(old_pill, new_pill)
        
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)

patch_file('c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\js\\agent_profiles.js')
patch_file('c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\js\\chat_engine.js')
print("Patched!")
