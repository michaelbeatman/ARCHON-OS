import os

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

target = """    <script>
      // =========================================================================
      // ?? ARCHON OS GLOBAL NOTIFICATION / TOAST SYSTEM
      // =========================================================================
      window.showNotification = function(title, message, type = "info") {
        if (typeof showArchonToast === 'function') {
          showArchonToast(message, type);
        } else {
          alert(title + ": " + message);
        }
      };
      // SKILL_MARKT.JS EXTRACTED
  
        // PROMPT_STUDIO.JS EXTRACTED
        // WISSENSBIBLIOTHEK.JS EXTRACTED
  
      // =========================================================================
      // THEME & CUSTOMIZATION (UI State & Sidebar Toggle)
      // =========================================================================
      let isSidebarCollapsed = false;
      function toggleSidebar() {
        const sb = document.getElementById('sidebar-container');
        if (sb) {
          isSidebarCollapsed = !isSidebarCollapsed;
          if (isSidebarCollapsed) {
            sb.style.width = '60px';
          } else {
            sb.style.width = 'var(--sidebar-width)';
          }
        }
      }
    </script>
    <!-- ========================================================================= -->"""

if "  </script>\n    <!-- ========================================================================= -->" in content:
    content = content.replace("  </script>\n    <!-- ========================================================================= -->", "    <!-- ========================================================================= -->")
    print("Fixed extra tag.")
else:
    print("Could not find the extra </script> tag.")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
