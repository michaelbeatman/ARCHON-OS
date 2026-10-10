const str = "This is a message.\n\n*- Routed to: `openai/gpt-4o-mini` | Tier: `High` | Est. Cost: `0.0001$`*";
const updatedRoutingRegex = /[\r\n\s]*\*\s*-\s*Routed to:\s*`?([^|`]+?)`?\s*\|\s*Tier:\s*`?([^|`]+?)`?\s*\|\s*Est\. Cost:\s*`?([^|`\n*]+?)`?\*?[\r\n\s]*$/i;
const originalRegex = /[\r\n\s]*\*?-\s*Routed to:\s*`?([^|`]+?)`?\s*\|\s*Tier:\s*`?([^|`]+?)`?\s*\|\s*Est\. Cost:\s*`?([^|`\n*]+?)`?\*?[\r\n\s]*$/i;
console.log("Original match:", !!str.match(originalRegex));
console.log("Original result:", str.match(originalRegex));
