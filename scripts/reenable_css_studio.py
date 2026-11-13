with open('static/js/css_live_studio.js', 'r', encoding='utf-8') as f:
    text = f.read()

norm_text = text.replace('\r\n', '\n')

old_part1 = """    window.ARCHON_LEGACY_STUDIO_DISABLED = true; // Ausgeklammert am 2026-10-16 zugunsten 15-Komponenten-System
    async function initArchonCssStudio() {
      if (window.ARCHON_LEGACY_STUDIO_DISABLED) {
        const legacyStyle = document.getElementById("archon-live-studio-style");
        if (legacyStyle) legacyStyle.remove();
        return;
      }"""

new_part1 = """    window.ARCHON_LEGACY_STUDIO_DISABLED = false;
    async function initArchonCssStudio() {"""

old_part2 = """    async function toggleCssStudio() {
      if (window.ARCHON_LEGACY_STUDIO_DISABLED) {
        if (typeof openSystemSettingsModal === "function") openSystemSettingsModal();
        if (typeof setSettingsTab === "function") setSettingsTab("design");
        return;
      }"""

new_part2 = """    async function toggleCssStudio() {"""

if old_part1 in norm_text:
    norm_text = norm_text.replace(old_part1, new_part1)
    print("Replaced part 1")
else:
    print("Warning: old_part1 not found!")

if old_part2 in norm_text:
    norm_text = norm_text.replace(old_part2, new_part2)
    print("Replaced part 2")
else:
    print("Warning: old_part2 not found!")

final_text = norm_text.replace('\n', '\r\n')
with open('static/js/css_live_studio.js', 'w', encoding='utf-8', newline='') as f:
    f.write(final_text)

print("Saved static/js/css_live_studio.js successfully!")
