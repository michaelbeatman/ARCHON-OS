with open('static/js/css_live_studio.js', 'r', encoding='utf-8') as f:
  c = f.read()
old_func = 'function toggleCssStudio() {'
new_func = 'async function toggleCssStudio() {\n      let studio = document.getElementById(\"archon-css-studio\");\n      if (!studio) {\n        try {\n          const r = await fetch(\"/static/views/view_app_frame_studio.html\");\n          const h = await r.text();\n          const m = document.getElementById(\"view-app-frame-studio-mount\");\n          if (m) m.outerHTML = h;\n          else {\n             const div = document.createElement(\"div\");\n             div.innerHTML = h;\n             document.body.appendChild(div);\n          }\n          studio = document.getElementById(\"archon-css-studio\");\n        } catch(e) {}\n      }'
c = c.replace(old_func, new_func)
with open('static/js/css_live_studio.js', 'w', encoding='utf-8') as f:
  f.write(c)
