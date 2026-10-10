$path = "static/index.html"
$content = Get-Content $path -Raw
$content = $content -replace 'chat_engine\.js\?v=\d+', 'chat_engine.js?v=202610082245'
$content = $content -replace 'agent_profiles\.js', 'agent_profiles.js?v=202610082245'
[IO.File]::WriteAllText($path, $content)
