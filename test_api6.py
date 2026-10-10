import urllib.request, json
req = urllib.request.Request("http://localhost:8501/api/debug-db")
print(urllib.request.urlopen(req).read().decode())
