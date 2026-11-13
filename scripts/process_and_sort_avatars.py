import os
import shutil
import glob
import json
import colorsys
import numpy as np
from PIL import Image

def get_bg_metrics(im):
    arr = np.array(im)
    top_left = arr[:25, :25].reshape(-1, 3)
    top_right = arr[:25, -25:].reshape(-1, 3)
    samples = np.vstack([top_left, top_right])
    med_rgb = np.median(samples, axis=0) / 255.0
    h, s, v = colorsys.rgb_to_hsv(*med_rgb)
    hex_color = '#{:02x}{:02x}{:02x}'.format(int(med_rgb[0]*255), int(med_rgb[1]*255), int(med_rgb[2]*255))
    return h, s, v, (med_rgb*255).astype(int), hex_color

def color_sort_key(item):
    h, s, v = item['hue'], item['sat'], item['val']
    deg = h * 360
    # Group 9: Neutral / Studio / Greyscale (low saturation)
    if s < 0.16:
        return (9, v, deg)
    # Group 8: Earthy / Warm brown
    if (15 <= deg <= 40) and (s < 0.45 or v < 0.55):
        return (8, v, deg)
    # Color spectrum
    if deg < 18 or deg >= 345:
        group = 0 # Rot
    elif deg < 45:
        group = 1 # Orange
    elif deg < 70:
        group = 2 # Gelb
    elif deg < 165:
        group = 3 # Grün
    elif deg < 200:
        group = 4 # Türkis
    elif deg < 260:
        group = 5 # Blau
    elif deg < 295:
        group = 6 # Lila
    elif deg < 345:
        group = 7 # Pink
    else:
        group = 0
    return (group, deg, -s, -v)

GROUP_NAMES = {
    0: ('rot', 'Rot'),
    1: ('orange', 'Orange'),
    2: ('gelb', 'Gelb'),
    3: ('gruen', 'Grün'),
    4: ('tuerkis', 'Türkis'),
    5: ('blau', 'Blau'),
    6: ('lila', 'Lila'),
    7: ('pink', 'Pink'),
    8: ('braun', 'Braun'),
    9: ('neutral', 'Neutral / Studio')
}

def main():
    avatars_dir = r'/path/to/archon-os'
    archive_dir = os.path.join(avatars_dir, 'archive_108')
    os.makedirs(archive_dir, exist_ok=True)
    
    # 1. Backup existing 108 avatars
    old_files = sorted(glob.glob(os.path.join(avatars_dir, 'avatar_*.jpg')))
    print(f'Backing up {len(old_files)} existing avatars to {archive_dir}...')
    for f in old_files:
        shutil.copy2(f, os.path.join(archive_dir, os.path.basename(f)))
        
    # 2. Extract 174 avatars from the 5 sheets
    sheet_paths = [
        r'C:/Users/User/.gemini/antigravity/brain/bff250d8-27ee-4678-bb46-91f8b6845482/.user_uploaded/media_1789322962127.jpg',
        r'C:/Users/User/.gemini/antigravity/brain/bff250d8-27ee-4678-bb46-91f8b6845482/.user_uploaded/media_1789322962128.jpg',
        r'C:/Users/User/.gemini/antigravity/brain/bff250d8-27ee-4678-bb46-91f8b6845482/.user_uploaded/media_1789322962136.jpg',
        r'C:/Users/User/.gemini/antigravity/brain/bff250d8-27ee-4678-bb46-91f8b6845482/.user_uploaded/media_1789322962142.jpg',
        r'C:/Users/User/.gemini/antigravity/brain/bff250d8-27ee-4678-bb46-91f8b6845482/.user_uploaded/media_1789322962185.jpg',
    ]
    
    all_items = []
    
    for p_idx, p in enumerate(sheet_paths):
        img = Image.open(p).convert('RGB')
        arr = np.array(img)
        col_mean = arr.mean(axis=(0, 2))
        row_mean = arr.mean(axis=(1, 2))
        
        non_gutters = np.where(col_mean <= 245)[0]
        ng_splits = np.where(np.diff(non_gutters) > 1)[0]
        cols = list(zip([non_gutters[0]] + [non_gutters[i+1] for i in ng_splits], [non_gutters[i] for i in ng_splits] + [non_gutters[-1]]))
        
        non_gutters_y = np.where(row_mean <= 245)[0]
        ng_splits_y = np.where(np.diff(non_gutters_y) > 1)[0]
        rows = list(zip([non_gutters_y[0]] + [non_gutters_y[i+1] for i in ng_splits_y], [non_gutters_y[i] for i in ng_splits_y] + [non_gutters_y[-1]]))
        
        for r_idx, (y1, y2) in enumerate(rows):
            for c_idx, (x1, x2) in enumerate(cols):
                cx1, cx2 = x1 + 2, x2 - 1
                cy1, cy2 = y1 + 2, y2 - 1
                w, h = cx2 - cx1, cy2 - cy1
                dim = min(w, h)
                sx = cx1 + (w - dim) // 2
                sy = cy1 + (h - dim) // 2
                cell = img.crop((sx, sy, sx + dim, sy + dim)).resize((256, 256), Image.Resampling.LANCZOS)
                h_val, s_val, v_val, rgb, hex_c = get_bg_metrics(cell)
                all_items.append({
                    'orig_name': f'sheet_{p_idx+1}_r{r_idx}_c{c_idx}',
                    'img': cell,
                    'hue': h_val,
                    'sat': s_val,
                    'val': v_val,
                    'rgb': rgb,
                    'hex': hex_c,
                    'is_new': True
                })

    print(f'Extracted {len(all_items)} new avatars from sheets.')
    
    # 3. Add existing 108 avatars
    for f in old_files:
        im = Image.open(f).convert('RGB')
        h_val, s_val, v_val, rgb, hex_c = get_bg_metrics(im)
        all_items.append({
            'orig_name': os.path.basename(f),
            'img': im,
            'hue': h_val,
            'sat': s_val,
            'val': v_val,
            'rgb': rgb,
            'hex': hex_c,
            'is_new': False
        })
        
    print(f'Total avatars to sort: {len(all_items)}')
    
    # 4. Sort all items by color
    sorted_items = sorted(all_items, key=color_sort_key)
    
    # 5. Save all items sequentially as avatar_001.jpg .. avatar_282.jpg
    metadata = []
    old_to_new_mapping = {}
    
    for idx, item in enumerate(sorted_items, 1):
        filename = f'avatar_{idx:03d}.jpg'
        out_path = os.path.join(avatars_dir, filename)
        item['img'].save(out_path, 'JPEG', quality=95)
        
        grp_idx = color_sort_key(item)[0]
        grp_code, grp_label = GROUP_NAMES.get(grp_idx, ('neutral', 'Neutral / Studio'))
        
        metadata.append({
            'id': f'avatar_{idx:03d}',
            'index': idx,
            'filename': filename,
            'url': f'/static/avatars/{filename}',
            'color_group': grp_code,
            'color_name': grp_label,
            'hex': item['hex'],
            'is_new': item['is_new']
        })
        
        if not item['is_new']:
            old_to_new_mapping[item['orig_name']] = filename
            
    # Save metadata JSON
    meta_path = os.path.join(avatars_dir, 'avatars_metadata.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
        
    print(f'Saved {len(metadata)} avatars and metadata to {avatars_dir}.')
    
    # Print color summary
    from collections import Counter
    counts = Counter([m['color_name'] for m in metadata])
    for grp, cnt in counts.items():
        print(f'  - {grp}: {cnt}')
        
    # Mapping table
    mapping_path = os.path.join(avatars_dir, 'old_to_new_mapping.json')
    with open(mapping_path, 'w', encoding='utf-8') as f:
        json.dump(old_to_new_mapping, f, indent=2)
        
    for target in ['avatar_009.jpg', 'avatar_019.jpg', 'avatar_033.jpg', 'avatar_083.jpg']:
        print(f'Mapping {target} -> {old_to_new_mapping.get(target)}')

    return old_to_new_mapping

if __name__ == '__main__':
    mapping = main()
