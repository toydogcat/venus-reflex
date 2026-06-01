import os
import json
import shutil
from pathlib import Path

BANK_DIR = Path('/home/toby/documents/projects/venus-reflex/bank/闇河魅影')

def process_volume(vol_name):
    vol_path = BANK_DIR / vol_name
    manifest_path = vol_path / 'manifest.json'
    pages_dir = vol_path / 'pages'
    assets_dir = vol_path / 'assets'
    
    if not manifest_path.exists():
        print(f"[{vol_name}] Skip: No manifest.json")
        return False
        
    # Read manifest
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
        
    page_count = manifest.get('page_count', 0)
    print(f"[{vol_name}] Starting removal of page 4. Current page count: {page_count}")
    
    # 1. Read page 4 to find the image file to delete
    p4_json_path = pages_dir / '0004.json'
    if not p4_json_path.exists():
        print(f"  [{vol_name}] ERROR: pages/0004.json not found!")
        return False
        
    with open(p4_json_path, 'r', encoding='utf-8') as f:
        p4_data = json.load(f)
        
    img_to_delete = None
    for el in p4_data.get('elements', []):
        if el.get('type') == 'image':
            img_to_delete = el.get('src')
            break
            
    # Delete page 4 JSON
    p4_json_path.unlink()
    
    # Delete page 4 image
    if img_to_delete:
        img_path = vol_path / img_to_delete
        if img_path.exists():
            img_path.unlink()
            print(f"  [{vol_name}] Deleted credit image: {img_to_delete}")
        else:
            print(f"  [{vol_name}] Warning: Image file {img_path} not found to delete.")
            
    # 2. Shift subsequent pages 5 to page_count down by 1
    # We do this in ascending order (5, 6, ..., page_count)
    for idx in range(5, page_count + 1):
        old_json_name = f"{idx:04d}.json"
        new_json_name = f"{(idx - 1):04d}.json"
        
        old_json_path = pages_dir / old_json_name
        new_json_path = pages_dir / new_json_name
        
        if not old_json_path.exists():
            print(f"  [{vol_name}] Warning: {old_json_name} not found during shift.")
            continue
            
        # Read the page JSON
        with open(old_json_path, 'r', encoding='utf-8') as f:
            page_data = json.load(f)
            
        # Update page_index
        page_data['page_index'] = idx - 1
        
        # Rename referenced image in elements if any
        for el in page_data.get('elements', []):
            if el.get('type') == 'image':
                old_src = el.get('src')
                if old_src:
                    # e.g., 'assets/img_0005.jpeg' -> we want 'assets/img_0004.jpeg'
                    old_img_path = vol_path / old_src
                    ext = Path(old_src).suffix
                    new_src = f"assets/img_{(idx - 1):04d}{ext}"
                    new_img_path = vol_path / new_src
                    
                    if old_img_path.exists():
                        # Rename the physical file
                        old_img_path.rename(new_img_path)
                    else:
                        print(f"  [{vol_name}] Warning: Image {old_img_path} not found to rename.")
                        
                    el['src'] = new_src
                    
        # Write the updated JSON to the new path
        with open(new_json_path, 'w', encoding='utf-8') as f:
            json.dump(page_data, f, ensure_ascii=False, indent=4)
            
        # Delete the old JSON file
        old_json_path.unlink()
        
    # 3. Update manifest.json
    manifest['page_count'] = page_count - 1
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=4)
        
    print(f"  [{vol_name}] Successfully completed. New page count: {manifest['page_count']}")
    return True

def main():
    volumes = sorted([d for d in os.listdir(BANK_DIR) if d.startswith('red_river_vol')])
    print(f"Found {len(volumes)} volumes to process.")
    
    success_count = 0
    for vol in volumes:
        try:
            if process_volume(vol):
                success_count += 1
        except Exception as e:
            print(f"ERROR processing volume {vol}: {e}")
            
    print(f"\nCompleted! Successfully processed {success_count} / {len(volumes)} volumes.")

if __name__ == '__main__':
    main()
