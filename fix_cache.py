with open('static/index.html', 'r', encoding='utf-8') as f:
  html = f.read()
html = html.replace('v=202610102000', 'v=202610101615')
with open('static/index.html', 'w', encoding='utf-8') as f:
  f.write(html)
