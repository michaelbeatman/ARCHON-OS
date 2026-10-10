import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\main.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

bad_block = '''@app.get("/")
def get_index():
    return FileResponse(

@app.get("/v2")
def get_index_v2():
    return FileResponse("static_v2/index.html")
        os.path.join("static", "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",'''

good_block = '''@app.get("/")
def get_index():
    return FileResponse(
        os.path.join("static", "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        }
    )

@app.get("/v2")
def get_index_v2():
    return FileResponse("static_v2/index.html")'''

# Need to handle whatever follows `headers={` to not overwrite too much, but the bad_block covers enough.
# Let's just use string replace.
# Actually `headers={` is followed by `"Pragma": "no-cache",`
# So let's replace exactly what we need.

bad_block2 = '''@app.get("/")
def get_index():
    return FileResponse(

@app.get("/v2")
def get_index_v2():
    return FileResponse("static_v2/index.html")
        os.path.join("static", "index.html"),
        headers={'''

good_block2 = '''@app.get("/v2")
def get_index_v2():
    return FileResponse("static_v2/index.html")

@app.get("/")
def get_index():
    return FileResponse(
        os.path.join("static", "index.html"),
        headers={'''

if bad_block2 in content:
    content = content.replace(bad_block2, good_block2)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Fixed get_index syntax error!")
else:
    print("Could not find bad block")
