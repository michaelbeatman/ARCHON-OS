import os
import re

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\js\\agent_profiles.js'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

target = '''    function isProfileDeployedActive(p) {
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
    }'''

replacement = '''    function isProfileDeployedActive(p) {
      if (typeof gwProfilesData !== 'undefined' && Array.isArray(gwProfilesData)) {
        const agent = gwProfilesData.find(gw => gw && gw.id === p.id);
        if (agent) {
          const st = (agent.status || '').toLowerCase().trim();
          if (st === 'active' || st === 'idle' || st === 'running') return true;
        }
      }
      if (typeof currentSelectedProfileId !== 'undefined' && p.id === currentSelectedProfileId) return true;
      if (typeof currentMasterChatProfileId !== 'undefined' && p.id === currentMasterChatProfileId) return true;
      if (p.id === 'default' || p.id === 'micha' || p.id === 'telegram_bot') return true;
      if (typeof masterChatSessions !== 'undefined' && Array.isArray(masterChatSessions)) {
         const hasSession = masterChatSessions.find(s => s && s.profile_name === p.id && (Date.now()/1000 - Number(s.last_activity_at || s.started_at || 0) < 86400));
         if (hasSession) return true;
      }
      return false;
    }'''

if target in c:
    c = c.replace(target, replacement)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)
    print("Agent profiles active check patched.")
else:
    print("Target not found")
