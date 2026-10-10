import os
main_path = r'C:\.Antigravity-projekte\AgenticOS-2026\main.py'
with open(main_path, 'r', encoding='utf8') as f:
    content = f.read()

themes_code = '''
THEMES_DIR = os.path.join(CONFIG_DIR, "themes")
os.makedirs(THEMES_DIR, exist_ok=True)

@app.get("/api/themes")
def api_get_themes():
    themes = []
    if os.path.exists(THEMES_DIR):
        for file in os.listdir(THEMES_DIR):
            if file.endswith(".json"):
                themes.append(file.replace(".json", ""))
    return {"themes": themes}

@app.get("/api/themes/{theme_name}")
def api_get_theme_by_name(theme_name: str):
    path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    if os.path.exists(path):
        return _load_json(path, {})
    return {}

@app.post("/api/themes/{theme_name}")
def api_save_theme_by_name(theme_name: str, theme_data: dict = Body(...)):
    path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    _save_json(path, theme_data)
    return {"status": "success", "theme_name": theme_name}

@app.delete("/api/themes/{theme_name}")
def api_delete_theme_by_name(theme_name: str):
    path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    if os.path.exists(path):
        os.remove(path)
    return {"status": "success"}
'''

# Find where to insert this
idx = content.find('@app.get("/api/theme")')
if idx != -1:
    content = content[:idx] + themes_code + '\n' + content[idx:]
    with open(main_path, 'w', encoding='utf8') as f:
        f.write(content)
    print("Injected themes endpoints successfully.")
else:
    print("Could not find anchor.")
