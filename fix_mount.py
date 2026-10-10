import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\index.html'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

# Remove the broken powershell ones
c = c.replace('<div id=\\ system-settings-mount\\></div>\n', '')
c = c.replace('<div id=\\ system-settings-mount\\></div>', '')
c = c.replace('<div id="system-settings-mount"></div>', '')

# Append correctly
c = c.replace('</body>', '<div id="system-settings-mount"></div>\n</body>')

with open(p, 'w', encoding='utf-8') as f:
    f.write(c)
print("Fixed system-settings-mount!")
