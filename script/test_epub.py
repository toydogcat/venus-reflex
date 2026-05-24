import zipfile
import sys
epub_path = sys.argv[1]
with zipfile.ZipFile(epub_path, 'r') as z:
    # List all image files
    images = [n for n in z.namelist() if n.endswith(('.jpg', '.jpeg', '.png', '.gif'))]
    print(f"Found {len(images)} images.")
    for img in sorted(images)[:5]:
        print(img)
