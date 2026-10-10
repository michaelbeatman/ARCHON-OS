const fs = require('fs');
let code = fs.readFileSync('static/js/agent_profiles.js', 'utf8');

const injection = `
              } else if (eventData.type === "done") {
                const updatedRoutingRegex = /[\\r\\n\\s]*\\*?-\\s*Routed to:\\s*\`?([^|\`]+?)\`?\\s*\\|\\s*Tier:\\s*\`?([^|\`]+?)\`?\\s*\\|\\s*Est\\. Cost:\\s*\`?([^|\`\\n*]+?)\`?\\*?[\\r\\n\\s]*$/i;
                const match = fullText.match(updatedRoutingRegex);
                if (match && bodyEl) {
                  fullText = fullText.replace(updatedRoutingRegex, '');
                  bodyEl.innerHTML = typeof formatMarkdownText === "function" ? formatMarkdownText(fullText) : escapeHtml(fullText);
                  
                  const routingTagHtml = \`<div class="flex items-center gap-1.5 w-fit">
                    <i data-lucide="cpu" class="w-3 h-3 text-indigo-400"></i>
                    <span class="truncate max-w-[200px]" title="\${match[1].trim()}">\${match[1].trim()}</span>
                    <span class="text-emerald-500 font-bold ml-1">\${match[2].trim()}</span>
                    <span class="text-amber-500 font-bold ml-1">\${match[3].trim()}</span>
                  </div>\`;
                  
                  const timeDiv = assistantBubble.querySelector('.pt-1\\\\.5.border-t');
                  if (timeDiv) {
                     const idDiv = timeDiv.querySelector('div:last-child');
                     if (idDiv) {
                       idDiv.insertAdjacentHTML('beforebegin', routingTagHtml);
                     } else {
                       timeDiv.insertAdjacentHTML('beforeend', routingTagHtml);
                     }
                  }
                  if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
                }
`;

code = code.replace(/} else if \(eventData\.type === "error"\) \{/, injection + '} else if (eventData.type === "error") {');
fs.writeFileSync('static/js/agent_profiles.js', code);
console.log("Done");
