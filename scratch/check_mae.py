import os
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

BANK_DIR = Path('/home/toby/documents/projects/venus-reflex/bank/闇河魅影')

def get_image_mae(path1, path2):
    try:
        with Image.open(path1) as img1, Image.open(path2) as img2:
            # Convert to grayscale and resize to same size (say, 500x700) for a robust check
            img1_gray = img1.convert('L').resize((500, 750))
            img2_gray = img2.convert('L').resize((500, 750))
            
            diff = ImageChops.difference(img1_gray, img2_gray)
            stat = ImageStat.Stat(diff)
            # Get average pixel difference (MAE)
            return stat.mean[0]
    except Exception as e:
        print(f"Error comparing {path1} and {path2}: {e}")
        return 255.0

def main():
    volumes = sorted([d for d in os.listdir(BANK_DIR) if d.startswith('red_river_vol')])
    print(f"Found {len(volumes)} volumes.")
    
    ref_vol = 'red_river_vol01'
    ref_img_path = BANK_DIR / ref_vol / 'assets' / 'img_0004.jpeg'
    
    if not ref_img_path.exists():
        print(f"Reference image {ref_img_path} does not exist.")
        return
        
    print(f"Reference: {ref_vol}/assets/img_0004.jpeg")
    
    for vol in volumes:
        vol_path = BANK_DIR / vol
        p4_json_path = vol_path / 'pages' / '0004.json'
        
        if not p4_json_path.exists():
            print(f"{vol}: pages/0004.json does not exist.")
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
            continue
            
        img_path = vol_path / img_src
        if not img_path.exists():
            print(f"{vol}: Image file {img_path} does not exist.")
            continue
            
        mae = get_image_mae(ref_img_path, img_path)
        # If MAE is less than 5.0 (which is less than 2% average difference), it is extremely similar!
        is_similar = mae < 5.0
        print(f"{vol}: MAE = {mae:.4f} -> {'SIMILAR' if is_similar else 'DIFFERENT'}")

if __name__ == '__main__':
    main()
