import os
from PIL import Image

src_path = "/projects/AgenticOS-2026/static/img/raw_logo.jpg"
if not os.path.exists(src_path):
    src_path = "/app/static/img/raw_logo.jpg"

print(f"Loading image from {src_path}...")
img = Image.open(src_path).convert("RGBA")

datas = img.getdata()
new_data = []

# Target color: Black (0, 0, 0)
target_r, target_g, target_b = 0, 0, 0

for item in datas:
    # Grayscale brightness (0 = pure black text, 255 = pure white background)
    brightness = int(0.299 * item[0] + 0.587 * item[1] + 0.114 * item[2])
    
    # Calculate opacity alpha
    # Near white (> 240) -> completely transparent (0)
    # Near black (< 30) -> completely opaque (255)
    if brightness >= 240:
        new_data.append((target_r, target_g, target_b, 0))
    elif brightness <= 30:
        new_data.append((target_r, target_g, target_b, 255))
    else:
        # Smooth alpha interpolation
        alpha = int((240 - brightness) / (240 - 30) * 255)
        new_data.append((target_r, target_g, target_b, max(0, min(255, alpha))))

img.putdata(new_data)

# Crop bounding box of non-transparent content
bbox = img.getbbox()
if bbox:
    pad = 12
    w, h = img.size
    crop_box = (
        max(0, bbox[0] - pad),
        max(0, bbox[1] - pad),
        min(w, bbox[2] + pad),
        min(h, bbox[3] + pad)
    )
    img = img.crop(crop_box)

print(f"Processed cropped logo size: {img.size}")

# Save to destination paths
targets = [
    "/projects/AgenticOS-2026/static/img/michael_beatman_logo.png",
    "/projects/AgenticOS-2026/static/hermes-webui/static/michael_beatman_logo.png",
    "/projects/AgenticOS-2026/static/hermes-webui/michael_beatman_logo.png",
    "/opt/data/michael_beatman_logo.png",
    "/opt/data/plugins/hermes-webui/static/michael_beatman_logo.png",
    "/opt/data/plugins/hermes-webui/static/img/michael_beatman_logo.png"
]

for t in targets:
    try:
        os.makedirs(os.path.dirname(t), exist_ok=True)
        img.save(t, format="PNG")
        print(f"Saved: {t} ({os.path.getsize(t)} bytes)")
    except Exception as e:
        print(f"Could not save {t}: {e}")

print("Pure black transparent logo generated successfully!")
