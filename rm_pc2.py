import os

p = '/app/static_v2/index.html'
if os.path.exists(p):
    with open(p, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    with open(p, 'w', encoding='utf-8') as f:
        for line in lines:
            if 'id: "paperclip-orchestrator"' not in line:
                f.write(line)
