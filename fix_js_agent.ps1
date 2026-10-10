$path = "static/js/agent_profiles.js"
$content = Get-Content $path -Raw
$find = '      async function onAgentTabModelChange(val) {
        if (val === "__CUSTOM__") {'
$replace = '      function updateAgentModelCostUI(provider, model) {
        const costEl = document.getElementById("agent-tab-model-cost");
        if (costEl && provider === "openrouter" && window.masterChatModelPrices && window.masterChatModelPrices[model]) {
          const p = window.masterChatModelPrices[model];
          costEl.innerHTML = `Input: <span class="text-emerald-400">$${(p.prompt_1m||0).toFixed(2)}/1M</span> | Output: <span class="text-amber-400">$${(p.completion_1m||0).toFixed(2)}/1M</span>`;
          costEl.classList.remove("hidden");
        } else if (costEl) {
          costEl.classList.add("hidden");
        }
      }

      async function onAgentTabModelChange(val) {
        if (val === "__CUSTOM__") {'
$content = $content.Replace($find, $replace)

$find2 = '      async function onAgentTabProviderChange(prov, preferredModel, skipSave = false) {
        currentAgentTabProvider = prov || "openrouter";
        const modelSelect = document.getElementById("agent-tab-model-select");'
$replace2 = '      async function onAgentTabProviderChange(prov, preferredModel, skipSave = false) {
        currentAgentTabProvider = prov || "openrouter";
        const modelSelect = document.getElementById("agent-tab-model-select");'
$content = $content.Replace($find2, $replace2)

$find3 = '        currentAgentTabModel = modelSelect.value;
        syncAgentHeaderModelDropdown();'
$replace3 = '        currentAgentTabModel = modelSelect.value;
        syncAgentHeaderModelDropdown();
        updateAgentModelCostUI(currentAgentTabProvider, currentAgentTabModel);'
$content = $content.Replace($find3, $replace3)

$find4 = '        currentAgentTabModel = val;
        syncAgentHeaderModelDropdown();'
$replace4 = '        currentAgentTabModel = val;
        syncAgentHeaderModelDropdown();
        updateAgentModelCostUI(currentAgentTabProvider, currentAgentTabModel);'
$content = $content.Replace($find4, $replace4)

[IO.File]::WriteAllText($path, $content)
