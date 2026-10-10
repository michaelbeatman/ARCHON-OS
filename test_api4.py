import json
import urllib.request
req = urllib.request.Request("http://localhost:8501/api/llm-providers/prices")
with urllib.request.urlopen(req) as response:
    print("API is up!")
