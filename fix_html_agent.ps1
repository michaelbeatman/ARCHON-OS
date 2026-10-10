$path = "static/views/agent_profiles_view.html"
$content = Get-Content $path -Raw
$find = '                            <option value="anthropic/claude-3.5-sonnet">anthropic/claude-3.5-sonnet</option>
                          </select>'
$replace = '                            <option value="anthropic/claude-3.5-sonnet">anthropic/claude-3.5-sonnet</option>
                          </select>
                          <span id="agent-tab-model-cost" class="ml-2 text-[10px] hidden font-mono"></span>'
$content = $content.Replace($find, $replace)
[IO.File]::WriteAllText($path, $content)
