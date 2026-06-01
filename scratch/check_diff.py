import os
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

BANK_DIR = Path('/home/toby/documents/projects/venus-reflex/bank/闇河魅影')

def get_image_mae(path1, path2):
    try:
        with Image.open(path1) as img1, Image.open(path2) as img2:
            img1_gray = img1.convert('L').resize((500, 750))
            img2_gray = img2.convert('L').resize((500, 750))
            diff = ImageChops.difference(img1_gray, img2_gray)
            stat = ImageStat.Stat(diff)
            return stat.mean[0]
    except Exception as e:
        return 255.0

def main():
    ref_img_path = BANK_DIR / 'red_river_vol01/assets/img_0004.jpeg'
    
    # Compare with page 10 (manga page) of vol01
    manga_img_path = BANK_DIR / 'red_river_vol01/assets/img_0010.jpeg'
    print(f"MAE of normal manga page 10 vs credit page 4: {get_image_mae(ref_img_path, manga_img_path):.4f}")
    
    # Compare with page 1 (cover page) of vol01
    cover_img_path = BANK_DIR / 'red_river_vol01/assets/img_0001.jpeg'
    print(f"MAE of cover page 1 vs credit page 4: {get_image_mae(ref_img_path, cover_img_path):.4f}")

if __name__ == '__main__':
    main()
