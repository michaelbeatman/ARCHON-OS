import re
with open('static/index.html', 'r', encoding='utf-8') as f: content = f.read()
content = re.sub(r'<button id=\"nav-master-chat\"', '<button id=\"nav-master-chat\" style=\"display: none;\"', content)
with open('static/index.html', 'w', encoding='utf-8') as f: f.write(content)
