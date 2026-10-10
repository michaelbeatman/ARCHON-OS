import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\js\\chat_engine.js'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

target = '''    function onMasterChatModelChanged(model) {
      currentMasterChatModel = model;
      updateMasterChatProfileUI();
    }'''

replacement = '''    function onMasterChatModelChanged(model) {
      currentMasterChatModel = model;
      updateMasterChatProfileUI();
      updateMasterChatModelCostUI();
    }

    function updateMasterChatModelCostUI() {
        const costEl = document.getElementById("master-chat-model-cost");
        if (!costEl) return;
        const prices = masterChatModelPrices[currentMasterChatModel];
        if (prices) {
            costEl.innerText = `${prices.prompt_1m.toFixed(2)}$ / ${prices.completion_1m.toFixed(2)}$`;
            costEl.classList.remove("hidden");
        } else {
            costEl.classList.add("hidden");
        }
    }'''

if target in c:
    c = c.replace(target, replacement)
else:
    print("Not found, already injected?")

# We also need to call updateMasterChatModelCostUI() in onMasterChatProviderChanged
target2 = '''      populateModelDropdown(modelSelect, models, preferredModel);
      currentMasterChatModel = modelSelect.value;
      updateMasterChatProfileUI();
    }'''

replacement2 = '''      populateModelDropdown(modelSelect, models, preferredModel);
      currentMasterChatModel = modelSelect.value;
      updateMasterChatProfileUI();
      updateMasterChatModelCostUI();
    }'''

if target2 in c:
    c = c.replace(target2, replacement2)

with open(p, 'w', encoding='utf-8') as f:
    f.write(c)
print("Injected masterchat cost ui!")
