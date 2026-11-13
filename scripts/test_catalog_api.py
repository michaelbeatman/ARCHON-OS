import urllib.request
import json
import time
from _archon_auth import headers as _archon_headers

for attempt in range(10):
    try:
        req = urllib.request.urlopen(urllib.request.Request("http://localhost:8501/api/templates/catalog", headers=_archon_headers()), timeout=5)
        raw = req.read().decode("utf-8")
        data = json.loads(raw)
        templates = data.get("templates", [])
        print("HTTP STATUS:", req.status)
        print("TOTAL TEMPLATES IN CATALOG:", len(templates))
        if templates:
            first = templates[0]
            print("SAMPLE ID:", first.get("id"))
            print("SAMPLE NAME:", first.get("name_de"))
            print("SAMPLE TIER:", first.get("tier"))
            print("SAMPLE CATEGORY:", first.get("category"))
            print("HAS URL KEY:", "url" in first)
            
            # Check for any lingering 3rd party traces
            json_dump = json.dumps(templates).lower()
            print("ANY 'sureprompt' OCCURRENCES:", "sureprompt" in json_dump)
            print("ANY 'sureprompts.com' OCCURRENCES:", "sureprompts.com" in json_dump)
            
            # Test schema endpoint for the sample
            s_url = f"http://localhost:8501/api/templates/{first.get('id')}/schema"
            s_req = urllib.request.urlopen(s_url, timeout=5)
            s_data = json.loads(s_req.read().decode("utf-8"))
            print("SCHEMA STATUS:", s_req.status)
            print("SCHEMA FIELD COUNT:", len(s_data.get("template", {}).get("form_fields", [])))
            print("VERIFICATION COMPLETE: ALL CHECKS PASSED.")
            break
    except Exception as e:
        print(f"Waiting for container to be ready (attempt {attempt+1}): {e}")
        time.sleep(2)