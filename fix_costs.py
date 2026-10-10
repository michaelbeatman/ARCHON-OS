import re
with open('/app/static/js/agent_profiles.js', 'r', encoding='utf-8') as f:
  content = f.read()
content = content.replace('function renderAgentProfilesList() {', 'function renderAgentProfilesList() {\n  setTimeout(() => { if(typeof updateAgentModelCostUI === \'function\') updateAgentModelCostUI(); }, 200);')
content = content.replace('function selectAgentProfile(id) {', 'function selectAgentProfile(id) {\n  setTimeout(() => { if(typeof updateAgentModelCostUI === \'function\') updateAgentModelCostUI(); }, 100);')
with open('/app/static/js/agent_profiles.js', 'w', encoding='utf-8') as f:
  f.write(content)

with open('/app/static/js/chat_engine.js', 'r', encoding='utf-8') as f:
  content = f.read()
content = re.sub(r'<div class="text-\[10px\] text-\[\var\(--muted-foreground\)\] mt-2 font-mono flex items-center gap-4">.*?</div>', '', content, flags=re.DOTALL)
content = content.replace('${msg.timestamp}</span>', '${msg.timestamp}</span>\n                ${msg.token_usage ? `<span class="ml-2 text-[9px] text-[var(--muted-foreground)] pl-2">${msg.token_usage.total_tokens || 0} Tok (In: ${msg.timestamp?"maybe":"no"}There should be ${msg.token_usage.prompt_tokens || 0}, Out: ${msg.token_usage.completion_tokens || 0})</span>` : \'\'}')
content = content.replace('${msg.timestamp?"maybe":"no"}There should be ${msg.token_usage.prompt_tokens || 0}', '${msg.token_usage.prompt_tokens || 0}')
with open('/app/static/js/chat_engine.js', 'w', encoding='utf-8') as f:
  f.write(content)
