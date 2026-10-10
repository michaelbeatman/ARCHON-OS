import urllib.request
print(urllib.request.urlopen('http://localhost:8501/api/chat/sessions').read())
