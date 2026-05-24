import os
import json
import zipfile
import shutil
from pathlib import Path
from PIL import Image
from opencc import OpenCC

# Paths
EPUB_PATH = Path("/home/toby/documents/projects/venus-reflex/raw/漫畫/哆啦A梦珍藏版(第一部卷1-卷6) (永恒的经典,一生的珍藏日本国民级漫画,豆瓣万人9.7高分评价官方授权Kindle正式上架) (藤子·F·不二雄) (z-library.sk, 1lib.sk, z-lib.sk).epub")
BANK_DIR = Path("/home/toby/documents/projects/venus-reflex/bank")
BOOK_ID = "doraemon_vol1_6"
DEST_DIR = BANK_DIR / BOOK_ID
ASSETS_DIR = DEST_DIR / "assets"
PAGES_DIR = DEST_DIR / "pages"

# Converter for Traditional Chinese
cc = OpenCC('s2twp') # Simplified to Traditional (Taiwan standard with phrases)

def convert_to_vbf():
    # 1. Setup Directories
    if DEST_DIR.exists():
        shutil.rmtree(DEST_DIR)
    ASSETS_DIR.mkdir(parents=True)
    PAGES_DIR.mkdir(parents=True)

    # 2. Extract Images
    image_list = []
    with zipfile.ZipFile(EPUB_PATH, 'r') as z:
        for info in z.infolist():
            if info.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                # Extract to assets
                ext = Path(info.filename).suffix
                # Flatten the filename to avoid directory issues in assets
                new_name = f"img_{len(image_list):04d}{ext}"
                with z.open(info) as source, open(ASSETS_DIR / new_name, 'wb') as target:
                    shutil.copyfileobj(source, target)
                image_list.append(new_name)
    
    image_list.sort() # Ensure they are in order if index was handled differently, 
                      # but here we used len(image_list) so they are naturally ordered.

    # 3. Create manifest.json
    title = cc.convert("哆啦A梦珍藏版(第一部卷1-卷6)")
    author = cc.convert("藤子·F·不二雄")
    manifest = {
        "id": BOOK_ID,
        "title": title,
        "author": author,
        "type": "comic",
        "direction": "rtl", # Japanese manga is usually RTL
        "page_count": len(image_list),
        "created_at": "2026-05-24T00:00:00Z"
    }
    with open(DEST_DIR / "manifest.json", 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=4)

    # 4. Create pages/*.json
    for i, img_name in enumerate(image_list):
        img_path = ASSETS_DIR / img_name
        with Image.open(img_path) as img:
            w, h = img.size
        
        page_data = {
            "page_index": i + 1,
            "width": w,
            "height": h,
            "elements": [
                {
                    "type": "image",
                    "src": f"assets/{img_name}",
                    "x": 0,
                    "y": 0,
                    "w": w,
                    "h": h,
                    "z_index": 0
                }
            ]
        }
        page_filename = f"{(i + 1):04d}.json"
        with open(PAGES_DIR / page_filename, 'w', encoding='utf-8') as f:
            json.dump(page_data, f, ensure_ascii=False, indent=4)

    print(f"Successfully converted {BOOK_ID} with {len(image_list)} pages.")

if __name__ == "__main__":
    convert_to_vbf()
