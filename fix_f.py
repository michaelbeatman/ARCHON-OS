import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\main.py'
with open(p, 'r', encoding='utf-8') as file:
    lines = file.readlines()

with open(p, 'w', encoding='utf-8') as file:
    for line in lines:
        if line.strip() == 'f':
            print("Removed dangling f")
            continue
        file.write(line)
