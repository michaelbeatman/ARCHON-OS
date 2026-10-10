import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\main.py'
with open(p, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(len(lines)):
    if '# logger.warning' in lines[i] or '# print' in lines[i]:
        if 'Paperclip' in lines[i]:
            lines[i] = lines[i].replace('# logger.warning', 'pass  # logger.warning').replace('# print', 'pass  # print')

with open(p, 'w', encoding='utf-8') as f:
    f.writelines(lines)
