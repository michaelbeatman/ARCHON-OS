import json
import urllib.request
req = urllib.request.Request("http://localhost:8501/api/chat/sessions/mc_20260927183941_brand_uiux_director/messages")
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode())
    print("Messages count:", len(data['messages']))
