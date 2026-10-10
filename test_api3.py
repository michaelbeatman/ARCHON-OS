import urllib.request
import json

req = urllib.request.Request("http://localhost:8501/api/chat/sessions/20260828_131801_1284dd5a/messages")
with urllib.request.urlopen(req) as response:
    print(response.read().decode())
