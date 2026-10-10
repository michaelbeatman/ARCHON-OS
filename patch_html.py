import os
p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\views\\master_chat_view.html'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

target = '''<option value="meta-llama/llama-3.3-70b-instruct" selected>meta-llama/llama-3.3-70b-instruct</option>
                      <option value="anthropic/claude-3.7-sonnet">anthropic/claude-3.7-sonnet</option>
                      <option value="openai/gpt-4o">openai/gpt-4o</option>
                      <option value="openai/gpt-4o-mini">openai/gpt-4o-mini</option>
                    </select>'''

replacement = '''<option value="meta-llama/llama-3.3-70b-instruct" selected>meta-llama/llama-3.3-70b-instruct</option>
                      <option value="anthropic/claude-3.7-sonnet">anthropic/claude-3.7-sonnet</option>
                      <option value="openai/gpt-4o">openai/gpt-4o</option>
                      <option value="openai/gpt-4o-mini">openai/gpt-4o-mini</option>
                    </select>
                    <span id="master-chat-model-cost" class="text-[9.5px] text-amber-500 font-mono font-bold ml-1.5 bg-amber-500/10 px-1.5 py-0.5 rounded hidden"></span>'''

if target in c:
    c = c.replace(target, replacement)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)
    print("Master chat HTML patched.")
else:
    print("Target not found in master_chat_view.html")
