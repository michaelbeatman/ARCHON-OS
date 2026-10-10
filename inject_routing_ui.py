import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views\system_settings_modal.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

injection_html = """          <!-- Divider -->
          <hr class="border-[var(--border)]">
          <!-- LLM Routing Policy (3-Tier) -->
          <div class="mt-4 mb-4">
            <h4 class="text-sm font-bold text-[var(--foreground)] mb-1 flex items-center gap-2">
              <i data-lucide="git-merge" class="w-4 h-4 text-emerald-500"></i> Automatische Routing Schwellenwerte (Kosten-Limits)
            </h4>
            <p class="text-[11px] text-[var(--muted-foreground)] leading-snug mb-3">
              Der CEO-Agent entscheidet dynamisch, welche LLM-Kostenstufe fr einen Task angemessen ist. Definiere hier die maximalen Kosten pro 1 Million Token fr die jeweilige Komplexittsstufe.
            </p>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
              <!-- Tier: Low -->
              <div class="p-3 border border-[var(--border)] rounded-xl bg-[var(--background)] flex flex-col gap-2 relative shadow-xs">
                <div class="absolute top-2 right-2 flex items-center gap-1.5 px-2 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono text-[10px] font-bold">
                  LOW
                </div>
                <label class="font-bold text-[var(--foreground)] text-xs flex items-center gap-1.5"><i data-lucide="zap" class="w-3.5 h-3.5 text-black dark:text-white"></i> Standard / Simple Tasks</label>
                <div class="flex items-center gap-2">
                  <span class="text-[var(--muted-foreground)] text-[10px] font-mono">Max $</span>
                  <input type="number" step="0.01" id="setting-routing-cap-low" value="0.10" class="w-full bg-[var(--input)] border border-[var(--border)] rounded text-xs px-2 py-1 text-[var(--foreground)] font-mono outline-none focus:border-[var(--ring)] transition" title="Max $ per 1M Tokens">
                  <span class="text-[var(--muted-foreground)] text-[10px] font-mono">/1M</span>
                </div>
                <p class="text-[10px] text-[var(--muted-foreground)] leading-tight">Erzwingt gnstige Modelle (z.B. OmniRoute Free-Tier oder Flash-Lite).</p>
              </div>

              <!-- Tier: Medium -->
              <div class="p-3 border border-[var(--border)] rounded-xl bg-[var(--background)] flex flex-col gap-2 relative shadow-xs">
                <div class="absolute top-2 right-2 flex items-center gap-1.5 px-2 py-0.5 rounded border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400 font-mono text-[10px] font-bold">
                  MEDIUM
                </div>
                <label class="font-bold text-[var(--foreground)] text-xs flex items-center gap-1.5"><i data-lucide="layers" class="w-3.5 h-3.5 text-black dark:text-white"></i> Standard Code &amp; Logic</label>
                <div class="flex items-center gap-2">
                  <span class="text-[var(--muted-foreground)] text-[10px] font-mono">Max $</span>
                  <input type="number" step="0.01" id="setting-routing-cap-medium" value="1.00" class="w-full bg-[var(--input)] border border-[var(--border)] rounded text-xs px-2 py-1 text-[var(--foreground)] font-mono outline-none focus:border-[var(--ring)] transition" title="Max $ per 1M Tokens">
                  <span class="text-[var(--muted-foreground)] text-[10px] font-mono">/1M</span>
                </div>
                <p class="text-[10px] text-[var(--muted-foreground)] leading-tight">Gutes Preis-Leistungs-Verhltnis (z.B. Haiku 3.5, Gemini Flash).</p>
              </div>

              <!-- Tier: High -->
              <div class="p-3 border border-[var(--border)] rounded-xl bg-[var(--background)] flex flex-col gap-2 relative shadow-xs border-indigo-500/30">
                <div class="absolute top-2 right-2 flex items-center gap-1.5 px-2 py-0.5 rounded border-indigo-500/30 bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-mono text-[10px] font-bold">
                  HIGH
                </div>
                <label class="font-bold text-[var(--foreground)] text-xs flex items-center gap-1.5"><i data-lucide="brain" class="w-3.5 h-3.5 text-black dark:text-white"></i> Complex Reasoning</label>
                <div class="flex items-center justify-center p-1.5 bg-[var(--secondary)] border border-[var(--border)] rounded border-dashed text-[10px] font-mono text-indigo-600 dark:text-indigo-400 font-bold">
                  NO CAP (USE BEST)
                </div>
                <p class="text-[10px] text-[var(--muted-foreground)] leading-tight">Ignoriert Kosten fr absolute Qualitt (z.B. GLM-5.3, Sonnet 3.5).</p>
              </div>
            </div>
          </div>
"""

target = '          <!-- Divider -->\n          <hr class="border-[var(--border)]">\n          <!-- Local OmniRoute Gateway Details -->'

new_content = content.replace(target, injection_html + target)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(new_content)
    
print("Successfully injected LLM Routing UI into system_settings_modal.html")
