import os
import time
from pathlib import Path
from PIL import Image

BANK_DIR = Path('/home/toby/documents/projects/venus-reflex/bank/闇河魅影')

def get_dir_size_and_count(directory):
    total_size = 0
    file_count = 0
    for root, dirs, files in os.walk(directory):
        for f in files:
            fp = os.path.join(root, f)
            if Path(f).suffix.lower() in ('.jpg', '.jpeg'):
                total_size += os.path.getsize(fp)
                file_count += 1
    return total_size, file_count

def main():
    print("Evaluating space occupied by JPEG assets...")
    total_size_bytes, total_files = get_dir_size_and_count(BANK_DIR)
    total_size_mb = total_size_bytes / (1024 * 1024)
    print(f"Total JPEG Files: {total_files}")
    print(f"Total JPEG Size: {total_size_mb:.2f} MB")
    
    if total_files == 0:
        print("No JPEG assets found.")
        return
        
    # Gather a representative sample of 20 images
    sample_images = []
    volumes = sorted([d for d in os.listdir(BANK_DIR) if d.startswith('red_river_vol')])
    
    count = 0
    for vol in volumes:
        assets_dir = BANK_DIR / vol / 'assets'
        if assets_dir.exists():
            for f in sorted(os.listdir(assets_dir)):
                if f.lower().endswith(('.jpg', '.jpeg')):
                    sample_images.append(assets_dir / f)
                    count += 1
                    if count >= 30: # Use 30 sample images across volumes
                        break
        if count >= 30:
            break
            
    print(f"\nEvaluating WebP compression on a sample of {len(sample_images)} images...")
    
    qualities = [75, 80, 85, 90]
    results = {q: {'size': 0, 'time': 0.0} for q in qualities}
    original_sample_size = sum(os.path.getsize(p) for p in sample_images)
    
    for img_path in sample_images:
        try:
            with Image.open(img_path) as img:
                # Convert to WebP under different qualities
                for q in qualities:
                    temp_webp = img_path.with_name(f"temp_eval_{q}.webp")
                    t0 = time.time()
                    img.save(temp_webp, 'WEBP', quality=q)
                    t1 = time.time()
                    
                    results[q]['size'] += os.path.getsize(temp_webp)
                    results[q]['time'] += (t1 - t0)
                    
                    # Clean up temp file
                    temp_webp.unlink()
        except Exception as e:
            print(f"Error evaluating {img_path}: {e}")
            
    print(f"\nCompression Results vs Original Sample ({original_sample_size / (1024*1024):.3f} MB):")
    for q in qualities:
        q_size = results[q]['size']
        q_size_mb = q_size / (1024 * 1024)
        saving_percent = (1 - (q_size / original_sample_size)) * 100
        extrapolated_size_mb = total_size_mb * (q_size / original_sample_size)
        extrapolated_saving_mb = total_size_mb - extrapolated_size_mb
        
        print(f"WebP Quality {q}:")
        print(f"  Sample Size: {q_size_mb:.3f} MB")
        print(f"  Space Savings: {saving_percent:.1f}%")
        print(f"  Avg Encode Time per Page: {(results[q]['time'] / len(sample_images)) * 1000:.1f} ms")
        print(f"  Extrapolated Total Size (28 vols): {extrapolated_size_mb:.2f} MB")
        print(f"  Extrapolated Total Space Saved: {extrapolated_saving_mb:.2f} MB")
        print()

if __name__ == '__main__':
    main()
