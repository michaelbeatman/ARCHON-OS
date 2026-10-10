$path = "main.py"
$content = Get-Content $path -Raw

$oldStr = '            import requests
            resp = requests.get("https://openrouter.ai/api/v1/models", timeout=5)
            if resp.status_code == 200:
                data = resp.json().get("data", [])'

$newStr = '            import urllib.request
            import json
            req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8")).get("data", [])'

$content = $content.Replace($oldStr, $newStr)
[IO.File]::WriteAllText($path, $content)
