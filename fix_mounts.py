with open('static/index.html', 'r', encoding='utf-8') as f:
  html = f.read()
html = html.replace('</body>', '<div id=\"system-settings-mount\"></div>\n</body>')
with open('static/index.html', 'w', encoding='utf-8') as f:
  f.write(html)
