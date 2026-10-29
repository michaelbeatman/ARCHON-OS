import re
import json
from pathlib import Path

BASE_DIR = Path(".")

def update_file(path: Path, transform_fn):
    if not path.exists():
        print(f"[SKIP] Datei existiert nicht: {path}")
        return
    content = path.read_text(encoding="utf-8")
    new_content = transform_fn(content)
    if new_content != content:
        path.write_text(new_content, encoding="utf-8")
        print(f"[OK] Aktualisiert: {path}")
    else:
        print(f"[INFO] Keine Aenderungen noetig: {path}")

def update_custom_css(content: str) -> str:
    # 1. Root token
    content = re.sub(
        r"--font-family:\s*['\"]Inter['\"][^;]*;",
        "--font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;",
        content
    )
    # 2. General typography rule: ensure Outfit fallback
    content = re.sub(
        r"font-family:\s*var\(--font-family\)\s*!important;",
        "font-family: var(--font-family, 'Outfit', sans-serif) !important;",
        content
    )
    # 3. Replace hardcoded Montserrat with inherit / Outfit
    content = re.sub(
        r"font-family:\s*['\"]Montserrat['\"],\s*sans-serif\s*!important;",
        "font-family: var(--font-family, 'Outfit', sans-serif) !important;",
        content
    )
    return content

def update_custom_studio_css(content: str) -> str:
    content = re.sub(
        r"font-family:\s*['\"]Montserrat['\"],\s*sans-serif\s*!important;",
        "font-family: var(--font-family, 'Outfit', sans-serif) !important;",
        content
    )
    return content

def update_themes_css(content: str) -> str:
    content = re.sub(
        r"--font-family:\s*['\"]Inter['\"],\s*sans-serif;",
        "--font-family: 'Outfit', sans-serif;",
        content
    )
    content = re.sub(
        r"font-family:\s*var\(--font-family,\s*['\"]Inter['\"],\s*sans-serif\)\s*!important;",
        "font-family: var(--font-family, 'Outfit', sans-serif) !important;",
        content
    )
    content = re.sub(
        r"font-family:\s*['\"]Inter['\"],\s*sans-serif\s*!important;",
        "font-family: var(--font-family, 'Outfit', sans-serif) !important;",
        content
    )
    return content

def update_index_html(content: str) -> str:
    # 1. Google Fonts Outfit weights: ensure 300..900
    content = re.sub(
        r"family=Outfit:wght@[0-9;]+",
        "family=Outfit:wght@300;400;500;600;700;800;900",
        content
    )
    # 2. Tailwind sans font family
    content = re.sub(
        r'sans:\s*\["Inter",\s*"-apple-system"',
        'sans: ["Outfit", "Inter", "-apple-system"',
        content
    )
    # 3. Add global Outfit override in head live styles
    replacement_style = """<style id="archon-live-custom-styles">
    :root {
      --font-family: 'Outfit', sans-serif !important;
    }
    html, body, button, input, select, textarea, p, h1, h2, h3, h4, h5, h6, label {
      font-family: var(--font-family, 'Outfit', sans-serif) !important;
    }
  </style>"""
    if '<style id="archon-live-custom-styles"></style>' in content:
        content = content.replace('<style id="archon-live-custom-styles"></style>', replacement_style)

    # 4. Quartz select defaults to Outfit
    content = re.sub(
        r'(<select id="quartz-cfg-font-header"[^>]*>[\s\S]*?)<option value="Outfit">Outfit</option>',
        r'\1<option value="Outfit" selected>Outfit</option>',
        content
    )
    content = re.sub(
        r'(<select id="quartz-cfg-font-body"[^>]*>[\s\S]*?)<option value="Outfit">Outfit</option>',
        r'\1<option value="Outfit" selected>Outfit</option>',
        content
    )
    return content

def update_customizer_js(content: str) -> str:
    content = re.sub(
        r"fontFamily:\s*['\"]'Inter',\s*sans-serif['\"]",
        "fontFamily: \"'Outfit', sans-serif\"",
        content
    )
    return content

def update_component_design_studio_js(content: str) -> str:
    # Migrate cached font in localStorage if it was Inter or Space Grotesk
    migration_snippet = """  // Auto-Migration to Outfit
  try {
    const cachedStore = localStorage.getItem("archon_cds_store_v1");
    if (cachedStore && (cachedStore.includes("'Inter'") || cachedStore.includes("'Space Grotesk'"))) {
      const fixed = cachedStore.replace(/'Inter',\\s*sans-serif/g, "'Outfit', sans-serif")
                               .replace(/'Space Grotesk',\\s*sans-serif/g, "'Outfit', sans-serif");
      localStorage.setItem("archon_cds_store_v1", fixed);
    }
  } catch(e) {}
"""
    if "Auto-Migration to Outfit" not in content:
        content = content.replace(
            "async function cdsInit() {",
            "async function cdsInit() {\n" + migration_snippet
        )
    return content

def update_app_frame_studio(content: str) -> str:
    # Set Outfit as selected default in st-select-font-family
    content = re.sub(
        r'<option value="\'Outfit\', sans-serif">Outfit \(Rund & Hochwertig\)</option>',
        r'<option value="\'Outfit\', sans-serif" selected>Outfit (Rund & Hochwertig)</option>',
        content
    )
    return content

def update_system_settings_modal(content: str) -> str:
    content = re.sub(
        r'<option value="\'Outfit\', sans-serif">Outfit</option>',
        r'<option value="\'Outfit\', sans-serif" selected>Outfit (Rund & Hochwertig)</option>',
        content
    )
    return content

def update_design_themes_json(path: Path):
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for tid, theme in data.get("themes", {}).items():
            for mode in ["light", "dark"]:
                mode_block = theme.get(mode, {})
                comps = mode_block.get("components", {})
                ws = comps.get("os-workspace", {}).get("normal", {})
                if ws.get("font-family") != "'Outfit', sans-serif":
                    ws["font-family"] = "'Outfit', sans-serif"
                    changed = True
        if changed:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[OK] design_themes.json aktualisiert: {path}")
        else:
            print(f"[INFO] design_themes.json war bereits auf Outfit: {path}")
    except Exception as e:
        print(f"[FEHLER] design_themes.json: {e}")

def main():
    print("=" * 60)
    print("SYSTEMWEITE UMSTELLUNG AUF 'OUTFIT' (RUND & HOCHWERTIG)")
    print("=" * 60)

    update_file(BASE_DIR / "static" / "custom.css", update_custom_css)
    update_file(BASE_DIR / "static" / "custom_studio.css", update_custom_studio_css)
    update_file(BASE_DIR / "static" / "css" / "themes.css", update_themes_css)
    update_file(BASE_DIR / "static" / "index.html", update_index_html)
    update_file(BASE_DIR / "static" / "js" / "customizer.js", update_customizer_js)
    update_file(BASE_DIR / "static" / "js" / "component_design_studio.js", update_component_design_studio_js)
    update_file(BASE_DIR / "static" / "views" / "view_app_frame_studio.html", update_app_frame_studio)
    update_file(BASE_DIR / "static" / "views" / "system_settings_modal.html", update_system_settings_modal)

    update_design_themes_json(BASE_DIR / "config" / "design_themes.json")
    update_design_themes_json(BASE_DIR / "data" / "design_themes.json")

    print("\n[FERTIG] Alle Kernkomponenten wurden auf 'Outfit' umgestellt.")

if __name__ == "__main__":
    main()
