import os
import re

p = '/app/main.py'
with open(p, 'r', encoding='utf-8') as f:
    code = f.read()

# Filter logic string
filter_logic = """
    ignore_patterns = [
        "Python 3 is missing from this system",
        "Launching a Python runner in internal mode",
        "TypeError fetch failed | getaddrinfo ENOTFOUND aihorde.net",
        "native fetch fallback ALSO failed",
        "combo trace combo-",
        "RuntimeError: The current task is not holding this lock",
        "Temporary failure in name resolution",
        "Telegram polling degraded",
        "Telegram network error",
        "All connection attempts failed",
        "failed initial connection after 3 attempts, parking until a reconnect is requested",
        "Server disconnected without sending a response"
    ]
    filtered_logs = []
    for line in logs.splitlines():
        if line.strip() and not any(p in line for p in ignore_patterns):
            filtered_logs.append(line)
    logs = "\\n".join(filtered_logs)
"""

# Patch get_container_logs_api
code = code.replace(
    'logs = parse_docker_stream(logs_raw)\n    return {"logs": logs}',
    'logs = parse_docker_stream(logs_raw)\n' + filter_logic + '\n    return {"logs": logs}'
)

# Patch get_all_container_logs_api
# Replace the inner loop logic
old_inner_loop = """
                parsed = parse_docker_stream(raw)
                for line in parsed.splitlines():
                    if line.strip():
                        combined_logs.append(f"[{c}] {line}")
"""

new_inner_loop = """
                parsed = parse_docker_stream(raw)
                ignore_patterns = [
                    "Python 3 is missing from this system",
                    "Launching a Python runner in internal mode",
                    "TypeError fetch failed | getaddrinfo ENOTFOUND aihorde.net",
                    "native fetch fallback ALSO failed",
                    "combo trace combo-",
                    "RuntimeError: The current task is not holding this lock",
                    "Temporary failure in name resolution",
                    "Telegram polling degraded",
                    "Telegram network error",
                    "All connection attempts failed",
                    "failed initial connection after 3 attempts, parking until a reconnect is requested",
                    "Server disconnected without sending a response"
                ]
                for line in parsed.splitlines():
                    if line.strip() and not any(p in line for p in ignore_patterns):
                        combined_logs.append(f"[{c}] {line}")
"""

if old_inner_loop in code:
    code = code.replace(old_inner_loop, new_inner_loop)
else:
    print("Could not find old_inner_loop")

# Also remove hermes-webui from containers since it's obsolete
code = code.replace('"hermes-webui", ', '')

with open(p, 'w', encoding='utf-8') as f:
    f.write(code)

