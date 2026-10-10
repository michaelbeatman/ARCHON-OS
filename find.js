const fs = require('fs');
const lines = fs.readFileSync('static/js/chat_engine.js', 'utf8').split('\n');
for (let i=0; i<lines.length; i++) {
    if (lines[i].includes('done')) {
        console.log("Found at:", i);
    }
}
