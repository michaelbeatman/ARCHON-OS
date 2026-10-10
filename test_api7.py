import urllib.request, json
try:
    req = urllib.request.Request("http://localhost:8501/api/chat/sessions")
    resp = urllib.request.urlopen(req).read().decode()
    data = json.loads(resp)
    print("Sessions:", len(data.get('sessions', [])))
except Exception as e:
    print("Error:", e)
