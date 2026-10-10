import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\js\\agent_profiles.js'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

update_func = '''
    function updateAgentModelCostUI() {
        const costEl = document.getElementById("agent-tab-model-cost");
        if (costEl && currentAgentTabModel) {
            if (window.masterChatModelPrices && window.masterChatModelPrices[currentAgentTabModel]) {
                const p = window.masterChatModelPrices[currentAgentTabModel];
                costEl.innerHTML = `Input: <span class="text-emerald-400">$${(p.prompt_1m||0).toFixed(2)}/1M</span> | Output: <span class="text-amber-400">$${(p.completion_1m||0).toFixed(2)}/1M</span>`;
                costEl.classList.remove("hidden");
            } else {
                costEl.classList.add("hidden");
            }
        }
    }
'''

target1 = 'currentAgentTabModel = val;'
replacement1 = 'currentAgentTabModel = val;\n      updateAgentModelCostUI();'

target2 = 'syncAgentHeaderModelDropdown();'
replacement2 = 'syncAgentHeaderModelDropdown();\n      updateAgentModelCostUI();'

if target1 in c:
    c = c.replace(target1, replacement1)
    
    # inject the function definition before onAgentTabModelChange
    target3 = 'async function onAgentTabModelChange(val) {'
    c = c.replace(target3, update_func + target3)
    
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)
    print("Agent profiles Cost UI patched.")
else:
    print("Target 1 not found")
