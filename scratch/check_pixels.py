import os
import json
from pathlib import Path
from PIL import Image, ImageChops

BANK_DIR = Path('/home/toby/documents/projects/venus-reflex/bank/闇河魅影')

def images_are_pixel_identical(path1, path2):
    try:
        with Image.open(path1) as img1, Image.open(path2) as img2:
            # If dimensions are different, they are not identical
            if img1.size != img2.size:
                return False
            # Check pixel difference
            diff = ImageChops.difference(img1, img2)
            return diff.getbbox() is None
    except Exception as e:
        print(f"Error comparing {path1} and {path2}: {e}")
        return False

def main():
    volumes = sorted([d for d in os.listdir(BANK_DIR) if d.startswith('red_river_vol')])
    print(f"Found {len(volumes)} volumes.")
    
    ref_vol = 'red_river_vol01'
    ref_img_path = BANK_DIR / ref_vol / 'assets' / 'img_0004.jpeg'
    
    if not ref_img_path.exists():
        print(f"Reference image {ref_img_path} does not exist.")
        return
        
    print(f"Reference: {ref_vol}/assets/img_0004.jpeg")
    
    identical_count = 0
    non_identical = []
    
    for vol in volumes:
        vol_path = BANK_DIR / vol
        p4_json_path = vol_path / 'pages' / '0004.json'
        
        if not p4_json_path.exists():
            print(f"{vol}: pages/0004.json does not exist.")
            non_identical.append((vol, "no json"))
            continue
            
        with open(p4_json_path, 'r', encoding='utf-8') as f:
            page_data = json.load(f)
        
        # Find image element
        img_src = None
        for el in page_data.get('elements', []):
            if el.get('type') == 'image':
                img_src = el.get('src')
                break
        
        if not img_src:
            print(f"{vol}: No image in pages/0004.json")
            non_identical.append((vol, "no image element"))
            continue
            
        img_path = vol_path / img_src
        if not img_path.exists():
            print(f"{vol}: Image file {img_path} does not exist.")
            non_identical.append((vol, "image file missing"))
            continue
            
        # Compare pixels
        is_same = images_are_pixel_identical(ref_img_path, img_path)
        if is_same:
            identical_count += 1
            print(f"{vol}: PIXEL IDENTICAL")
        else:
            non_identical.append((vol, "different pixels or size"))
            print(f"{vol}: DIFFERENT")
            
    print(f"\nSummary: {identical_count} / {len(volumes)} are pixel-identical to reference.")
    if non_identical:
        print(f"Different volumes: {non_identical}")

if __name__ == '__main__':
    main()
