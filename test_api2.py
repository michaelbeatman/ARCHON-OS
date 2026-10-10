import json
import urllib.request
req = urllib.request.Request("http://localhost:8501/api/chat/sessions")
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode())
    for s in data['sessions'][:5]:
        print(s['id'])
