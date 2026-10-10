import os

p = '/app/main.py'
with open(p, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(len(lines)):
    if '"paperclip-orchestrator"' in lines[i] and 'containers =' in lines[i]:
        lines[i] = lines[i].replace(', "paperclip-orchestrator"', '')

with open(p, 'w', encoding='utf-8') as f:
    f.writelines(lines)
