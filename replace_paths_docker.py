import os

def replace_static(folder):
    for root, dirs, files in os.walk(folder):
        for f in files:
            if not f.endswith(('.html', '.js', '.css')):
                continue
            p = os.path.join(root, f)
            try:
                with open(p, 'r', encoding='utf-8') as file:
                    content = file.read()
                if '/static_v2/' in content:
                    content = content.replace('/static_v2/', '/static/')
                    with open(p, 'w', encoding='utf-8') as file:
                        file.write(content)
            except Exception as e:
                print(f"Failed {p}: {e}")

replace_static('/app/static')
