import re

with open("static/index.html", "r", encoding="utf-8") as f:
    text = f.read()

views = set(re.findall(r'id=[\"\'](view-[a-zA-Z0-9_\-]+)[\"\']', text))
print("Total views:", len(views))
for v in sorted(views):
    print("  ", v)
