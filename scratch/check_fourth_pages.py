import os
import json
import hashlib
from pathlib import Path

BANK_DIR = Path('/home/toby/documents/projects/venus-reflex/bank/闇河魅影')

def get_md5(file_path):
    if not os.path.exists(file_path):
        return None
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def main():
    volumes = sorted([d for d in os.listdir(BANK_DIR) if d.startswith('red_river_vol')])
    print(f"Found {len(volumes)} volumes.")
    
    hashes = {}
    for vol in volumes:
        vol_path = BANK_DIR / vol
        p4_json_path = vol_path / 'pages' / '0004.json'
        
        if not p4_json_path.exists():
            print(f"{vol}: pages/0004.json does not exist.")
            continue
            
        try:
            with open(p4_json_path, 'r', encoding='utf-8') as f:
                page_data = json.load(f)
            
            # Find image element
            img_src = None
            for el in page_data.get('elements', []):
                if el.get('type') == 'image':
                    img_src = el.get('src')
                    break
            
            if not img_src:
                print(f"{vol}: No image element in pages/0004.json")
                continue
                
            img_path = vol_path / img_src
            if not img_path.exists():
                print(f"{vol}: Image file {img_path} does not exist.")
                continue
                
            file_hash = get_md5(img_path)
            file_size = os.path.getsize(img_path)
            hashes[vol] = (img_src, file_hash, file_size)
            print(f"{vol}: {img_src} -> md5: {file_hash}, size: {file_size} bytes")
        except Exception as e:
            print(f"{vol}: Error processing: {e}")
            
    # Check if they are all identical
    hash_values = [info[1] for info in hashes.values()]
    if len(set(hash_values)) == 1:
        print("\nSUCCESS: All page 4 images are EXACTLY IDENTICAL!")
        print(f"MD5: {hash_values[0]}")
    else:
        print(f"\nWARNING: Not all page 4 images are identical. Unique hashes found: {len(set(hash_values))}")
        # Group by hash
        groups = {}
        for vol, info in hashes.items():
            h = info[1]
            groups.setdefault(h, []).append(vol)
        for h, vols in groups.items():
            print(f"Hash {h} (size {hashes[vols[0]][2]} bytes) is shared by {len(vols)} vols: {vols[:5]}...")

if __name__ == '__main__':
    main()
