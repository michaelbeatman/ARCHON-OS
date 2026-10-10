import re
text = "Entschuldige bitte, da ist wohl etwas untergegangen. Auf welche Nachricht oder welchen Auftrag beziehst du dich genau? \n\nGib mir kurz einen Hinweis, damit ich das sofort prüfen oder den entsprechenden Agenten noch einmal anstupsen kann.\n\n*- Routed to: `auto/best-free` | Tier: `Low` | Est. Cost: `0.0000$`*"
regex = re.compile(r"\n*\*?\-\s*Routed to:\s*`?([^`|]+?)`?\s*\|\s*Tier:\s*`?([^`|]+?)`?\s*\|\s*Est\. Cost:\s*`?([^\n*`]+?)`?\s*\*?(?=\n|$)", re.IGNORECASE)
m = regex.search(text)
print("MATCH:", m.groups() if m else "None")
