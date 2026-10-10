import os
import re

f1 = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\static\\js\\agent_profiles.js'
with open(f1, 'r', encoding='utf-8') as f:
    c = f.read()

# find where it formats the html for agent bubble
target = '''        div.innerHTML = `
          <div class="flex gap-2.5 max-w-[90%]">'''

replacement = '''        let routingTagHtml = "";
        const updatedRoutingRegex = /[\\r\\n\\s]*\\*?-\\s*Routed to:\\s*`?([^|`]+?)`?\\s*\\|\\s*Tier:\\s*`?([^|`]+?)`?\\s*\\|\\s*Est\\. Cost:\\s*`?([^|`\\n*]+?)`?\\*?[\\r\\n\\s]*$/i;
        const match = safeContent.match(updatedRoutingRegex);
        let finalContent = safeContent;
        if (match) {
            finalContent = safeContent.replace(updatedRoutingRegex, '');
            routingTagHtml = `<div class="flex items-center gap-1.5 border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 rounded-md w-fit">
              <i data-lucide="cpu" class="w-3 h-3 text-indigo-400"></i>
              <span class="truncate max-w-[200px]" title="${match[1].trim()}">${match[1].trim()}</span>
              <span class="text-emerald-500 font-bold ml-1">${match[2].trim()}</span>
              <span class="text-amber-500 font-bold ml-1">${match[3].trim()}</span>
            </div>`;
        }

        div.innerHTML = `
          <div class="flex gap-2.5 max-w-[90%]">'''

if target in c:
    c = c.replace(target, replacement)
    
    # replace safeContent with finalContent inside the markdown formatting
    old_markdown = '${typeof formatMarkdownText === "function" ? formatMarkdownText(safeContent) : escapeHtml(safeContent)}'
    new_markdown = '${typeof formatMarkdownText === "function" ? formatMarkdownText(finalContent) : escapeHtml(finalContent)}'
    c = c.replace(old_markdown, new_markdown)

    # append routingTagHtml to the footer
    old_footer = '''              <div class="pt-1.5 border-t border-[var(--border)] flex items-center justify-between gap-2 text-[9px] font-mono text-[var(--muted-foreground)]">
                <span class="flex items-center gap-1 shrink-0"><i data-lucide="clock" class="w-2.5 h-2.5 text-black dark:text-white"></i>${dateFormatted}</span>
                <span class="shrink-0 font-medium">${idStr}</span>
              </div>'''
    new_footer = '''              <div class="pt-1.5 border-t border-[var(--border)] flex items-center justify-between gap-2 text-[9px] font-mono text-[var(--muted-foreground)] flex-wrap">
                <div class="flex items-center gap-1 shrink-0"><i data-lucide="clock" class="w-2.5 h-2.5 text-black dark:text-white"></i>${dateFormatted}</div>
                ${routingTagHtml}
                <div class="shrink-0 font-medium">${idStr}</div>
              </div>'''
    c = c.replace(old_footer, new_footer)

    with open(f1, 'w', encoding='utf-8') as f:
        f.write(c)
    print("Agent bubble regex added!")
else:
    print("Target not found")
