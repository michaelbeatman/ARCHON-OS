import os

p = '/app/static_v2/js/agent_profiles.js'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

old_isProfile = """    function isProfileDeployedActive(p) {
      const agent = getProfilePaperclipAgent(p);
      if (!agent) return false;
      const st = (agent.status || '').toLowerCase().trim();
      return st === 'active' || st === 'idle' || st === 'running';
    }"""

new_isProfile = """    function isProfileDeployedActive(p) {
      // 1. Check OmniRoute Gateway
      if (typeof gwProfilesData !== 'undefined' && Array.isArray(gwProfilesData)) {
        const agent = gwProfilesData.find(gw => gw && gw.id === p.id);
        if (agent) {
          const st = (agent.status || '').toLowerCase().trim();
          if (st === 'active' || st === 'idle' || st === 'running') return true;
        }
      }
      
      // 2. Check if user is currently chatting with them
      if (typeof currentSelectedProfileId !== 'undefined' && p.id === currentSelectedProfileId) return true;
      if (typeof currentMasterChatProfileId !== 'undefined' && p.id === currentMasterChatProfileId) return true;
      
      // 3. The 'default' (Master) is practically always active when you interact with it
      if (p.id === 'default' && (currentSelectedProfileId === 'default' || currentMasterChatProfileId === 'default')) return true;
      
      return false;
    }"""

c = c.replace(old_isProfile, new_isProfile)

old_loadAgents = """    async function loadPaperclipActiveAgents() {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 15000);
        const res = await fetch('/api/paperclip/agents', { signal: controller.signal });
        clearTimeout(timeoutId);
        const data = await res.json();
        if (data.status === 'success' && Array.isArray(data.agents)) {
          dynamicPaperclipAgents = data.agents;
          dynamicPaperclipAgentIds = data.agents
            .filter(a => {
              const st = (a.status || '').toLowerCase().trim();
              return st === 'active' || st === 'idle' || st === 'running';
            })
            .map(a => (a.profile_id || a.role || a.name || '').toLowerCase().trim())
            .filter(Boolean);
        }
      } catch (err) {
        console.warn('Paperclip sync fehlgeschlagen:', err);
      }
    }"""

new_loadAgents = """    async function loadPaperclipActiveAgents() {
      try {
        if (typeof fetchGatewayProfiles === 'function') {
           await fetchGatewayProfiles();
        }
      } catch (err) {
        console.warn('Gateway sync fehlgeschlagen:', err);
      }
    }"""

c = c.replace(old_loadAgents, new_loadAgents)

with open(p, 'w', encoding='utf-8') as f:
    f.write(c)
