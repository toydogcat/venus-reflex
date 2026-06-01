import os
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

BANK_DIR = Path('/home/toby/documents/projects/venus-reflex/bank/闇河魅影')

def get_image_mae(path1, path2):
    try:
        with Image.open(path1) as img1, Image.open(path2) as img2:
            if img1.size != img2.size:
                return 255.0 # different sizes
            img1_gray = img1.convert('L')
            img2_gray = img2.convert('L')
            diff = ImageChops.difference(img1_gray, img2_gray)
            stat = ImageStat.Stat(diff)
            return stat.mean[0]
    except Exception as e:
        return 255.0

def main():
    volumes = sorted([d for d in os.listdir(BANK_DIR) if d.startswith('red_river_vol')])
    print(f"Found {len(volumes)} volumes.")
    
    for vol in volumes:
        vol_path = BANK_DIR / vol
        p1_json_path = vol_path / 'pages' / '0001.json'
        p2_json_path = vol_path / 'pages' / '0002.json'
        
        if not p1_json_path.exists() or not p2_json_path.exists():
            print(f"{vol}: page 1 or page 2 does not exist.")
            continue
            
        # Get image paths
        with open(p1_json_path, 'r', encoding='utf-8') as f:
            p1_data = json.load(f)
        with open(p2_json_path, 'r', encoding='utf-8') as f:
            p2_data = json.load(f)
            
        img1_src = next((el.get('src') for el in p1_data.get('elements', []) if el.get('type') == 'image'), None)
        img2_src = next((el.get('src') for el in p2_data.get('elements', []) if el.get('type') == 'image'), None)
        
        if not img1_src or not img2_src:
            print(f"{vol}: missing image in page 1 or page 2 JSON.")
            continue
            
        img1_path = vol_path / img1_src
        img2_path = vol_path / img2_src
        
        if not img1_path.exists() or not img2_path.exists():
            print(f"{vol}: image files do not exist.")
            continue
            
        mae = get_image_mae(img1_path, img2_path)
        is_same = mae == 0.0 # exact pixel match
        is_extremely_similar = mae < 1.0 # minor compression difference
        
        print(f"{vol}: MAE between P1 ({img1_src}) and P2 ({img2_src}) = {mae:.4f} -> Same? {is_same} (Similar? {is_extremely_similar})")

if __name__ == '__main__':
    main()
