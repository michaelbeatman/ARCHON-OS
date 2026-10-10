import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\views\\master_chat_view.html'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

target = '''                  </select>
                </div>
                <!-- Center: Upload / Status Indicator -->'''

replacement = '''                  </select>
                  <span id="master-chat-model-cost" class="text-[9.5px] text-amber-500 font-mono font-bold ml-1.5 bg-amber-500/10 px-1.5 py-0.5 rounded hidden"></span>
                </div>
                <!-- Center: Upload / Status Indicator -->'''

if target in c:
    c = c.replace(target, replacement)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)
    print("Master chat HTML cost span patched.")
else:
    print("Target not found")
