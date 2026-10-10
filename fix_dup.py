with open('static/views/view_design_system.html', 'r', encoding='utf-8') as f:
  html = f.read()
html = html.replace('<div id=\"system-settings-mount\"></div>', '')
with open('static/views/view_design_system.html', 'w', encoding='utf-8') as f:
  f.write(html)
