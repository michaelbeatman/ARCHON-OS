import os

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = '      window.__archon_initialized = true;'

injection = '''
      // --- V2 COMPONENT FETCHES ---
      try {
        await Promise.all([
          fetch('/static_v2/views/system_settings_modal.html').then(r => r.text()).then(html => { const el = document.getElementById('system-settings-mount'); if (el) el.outerHTML = html; }),
          fetch('/static_v2/views/agent_profiles_view.html').then(r => r.text()).then(html => { const el = document.getElementById('view-agent-profiles-mount'); if (el) el.outerHTML = html; }),
          fetch('/static_v2/views/master_chat_view.html').then(r => r.text()).then(html => { const el = document.getElementById('view-master-chat-mount'); if (el) el.outerHTML = html; }),
          fetch('/static_v2/views/operations_view.html').then(r => r.text()).then(html => { const el = document.getElementById('view-operations-mount'); if (el) el.outerHTML = html; }),
          fetch('/static_v2/views/library_view.html').then(r => r.text()).then(html => { const el = document.getElementById('view-library-mount'); if (el) el.outerHTML = html; }),
          fetch('/static_v2/views/inbox_view.html').then(r => r.text()).then(html => { const el = document.getElementById('view-inbox-mount'); if (el) el.outerHTML = html; })
        ]);
      } catch(err) {
        console.error("V2 Fetch Error: ", err);
      }
      // -----------------------------
'''

if target in content:
    content = content.replace(target, target + injection)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Injected fetch logic into initArchonApp!")
else:
    print("Could not find initArchonApp")
