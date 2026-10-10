import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\main.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

# Replace the bad line
bad_line = "for m in re.finditer(r'hermes\\s+-p\\s+([a-zA-Z0-9_-]+)\\s+chat.*?-q\\s+[\"\\'](.*?)(?=[\"\\'](?:\\s|$))', full_assistant_text, re.DOTALL):"
good_line = '            for m in re.finditer(r\'hermes\\s+-p\\s+([a-zA-Z0-9_-]+)\\s+chat.*?-q\\s+["\\\\\'](.*?)(?=["\\\\\'](?:\\s|$))\', full_assistant_text, re.DOTALL):'

# Actually, the simplest way is to just use a triple quoted raw string or normal string.
# Let's just find the regex line by the start:
lines = c.split('\n')
for i, l in enumerate(lines):
    if "for m in re.finditer" in l and "hermes" in l:
        lines[i] = '            for m in re.finditer(r\'hermes\\s+-p\\s+([a-zA-Z0-9_-]+)\\s+chat.*?-q\\s+["\\\'](.*?)(?=["\\\'](?:\\s|$))\', full_assistant_text, re.DOTALL):'

with open(p, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print("Fixed syntax")
