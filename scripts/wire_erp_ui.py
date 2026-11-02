"""
scripts/wire_erp_ui.py
Repariert den Script-Tag-Einschub in `static/index.html` (entfernt ihn aus dem Template-String
auf Zeile 5383 und platziert ihn vor dem letzten </body> am Dateiende).
"""

import os

INDEX_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "index.html")


def main():
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # Entferne fälschlich im Template-Literal eingefügtes <script>-Tag
    html = html.replace('  <script src="/static/erp_studio.js?v=2026110112"></script>\n', "")

    # Füge es ausschließlich vor dem ALLERLETZTEN </body> am Dateiende ein
    last_body_idx = html.rfind("</body>")
    assert last_body_idx != -1, "Kein </body> am Dateiende gefunden"
    html = (
        html[:last_body_idx]
        + '  <script src="/static/erp_studio.js?v=2026110112"></script>\n'
        + html[last_body_idx:]
    )

    with open(INDEX_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    print("[+] static/index.html Script-Position erfolgreich repariert.")


if __name__ == "__main__":
    main()
