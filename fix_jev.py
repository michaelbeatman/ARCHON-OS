import re
import glob
for file in glob.glob('static/**/*.html', recursive=True):
  try:
    with open(file, 'r', encoding='utf-8') as f: content = f.read()
    if 'JEV' in content:
      content = content.replace('JEV Fast-Routing', 'PreDecision Fast-Routing').replace('JEV Einstellung', 'PreDecision Einstellung').replace('>JEV (TypeSafe', '>PreDecision (TypeSafe').replace('JEV Modell', 'PreDecision Modell').replace('JEV', 'PreDecision')
      with open(file, 'w', encoding='utf-8') as f: f.write(content)
  except Exception as e: pass

