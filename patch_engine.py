import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\js\\chat_engine.js'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

target = 'if (currentMasterChatProvider === "openrouter" && masterChatModelPrices[currentMasterChatModel]) {'
replacement = 'if (masterChatModelPrices[currentMasterChatModel]) {'

if target in c:
    c = c.replace(target, replacement)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)
    print("chat_engine.js patched for cost condition.")
else:
    print("Target not found")
