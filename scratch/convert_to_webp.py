import os
import json
import time
from pathlib import Path
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

SRC_DIR = Path('/home/toby/documents/projects/venus-reflex/bank/闇河魅影')
DST_DIR = Path('/home/toby/documents/projects/venus-reflex/bank/闇河魅影（web）')

def process_volume(vol_name):
    src_vol_path = SRC_DIR / vol_name
    dst_vol_path = DST_DIR / vol_name
    
    src_manifest = src_vol_path / 'manifest.json'
    if not src_manifest.exists():
        print(f"[{vol_name}] Skip: No manifest.json found.")
        return False
        
    print(f"[{vol_name}] Starting WebP Quality 80 conversion...")
    
    # 1. Re-create destination dirs cleanly
    if dst_vol_path.exists():
        import shutil
        shutil.rmtree(dst_vol_path)
    
    dst_pages_dir = dst_vol_path / 'pages'
    dst_assets_dir = dst_vol_path / 'assets'
    dst_pages_dir.mkdir(parents=True)
    dst_assets_dir.mkdir(parents=True)
    
    # 2. Read and modify manifest
    with open(src_manifest, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
        
    # Extract volume number from folder name
    vol_num = vol_name[-2:]
    
    manifest['id'] = f"red_river_vol{vol_num}_web"
    manifest['title'] = f"赤河戀影 {vol_num} [Web]"
    manifest['category'] = "闇河魅影（web）"
    
    with open(dst_vol_path / 'manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=4)
        
    # 3. Process all pages
    src_pages_dir = src_vol_path / 'pages'
    pages = sorted(os.listdir(src_pages_dir))
    
    t0 = time.time()
    converted_count = 0
    
    for page_file in pages:
        if not page_file.endswith('.json'):
            continue
            
        src_page_path = src_pages_dir / page_file
        dst_page_path = dst_pages_dir / page_file
        
        with open(src_page_path, 'r', encoding='utf-8') as f:
            page_data = json.load(f)
            
        # Convert image
        for el in page_data.get('elements', []):
            if el.get('type') == 'image':
                src_img_rel = el.get('src')
                if src_img_rel:
                    src_img_path = src_vol_path / src_img_rel
                    
                    # Target WebP filename
                    page_idx_str = Path(page_file).stem # e.g. '0001'
                    dst_img_rel = f"assets/img_{page_idx_str}.webp"
                    dst_img_path = dst_vol_path / dst_img_rel
                    
                    if src_img_path.exists():
                        try:
                            # Convert JPEG to WebP Quality 80
                            with Image.open(src_img_path) as img:
                                img.save(dst_img_path, 'WEBP', quality=80)
                            converted_count += 1
                        except Exception as e:
                            print(f"  [{vol_name}] Error converting image {src_img_path}: {e}")
                    else:
                        print(f"  [{vol_name}] Warning: Source image {src_img_path} not found.")
                        
                    el['src'] = dst_img_rel
                    
        # Write updated JSON to destination
        with open(dst_page_path, 'w', encoding='utf-8') as f:
            json.dump(page_data, f, ensure_ascii=False, indent=4)
            
    t1 = time.time()
    print(f"[{vol_name}] Finished! Converted {converted_count} pages in {t1 - t0:.2f} seconds.")
    return True

def main():
    if not DST_DIR.exists():
        DST_DIR.mkdir(parents=True)
        
    volumes = sorted([d for d in os.listdir(SRC_DIR) if d.startswith('red_river_vol')])
    print(f"Found {len(volumes)} volumes to convert concurrently.")
    
    t_start = time.time()
    
    # Process volumes in parallel using up to 8 threads
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(process_volume, volumes))
        
    success_count = sum(1 for r in results if r)
    t_end = time.time()
    print(f"\nMigration completed! Successfully converted {success_count} / {len(volumes)} volumes in {t_end - t_start:.2f} seconds.")

if __name__ == '__main__':
    main()
