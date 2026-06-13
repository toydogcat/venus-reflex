#!/usr/bin/env python3
import os
import sys

# Repository subpath for GitHub Pages
BASE_PATH = "/venus-reflex"

def patch_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Skipping {file_path} (could not read): {e}")
        return

    # Replacements list
    replacements = [
        # Double quotes
        ('"/assets/', f'"{BASE_PATH}/assets/'),
        ('"/bgm.mp3"', f'"{BASE_PATH}/bgm.mp3"'),
        ('"/favicon.ico"', f'"{BASE_PATH}/favicon.ico"'),
        ('"/cache/', f'"{BASE_PATH}/cache/'),
        ('"/bank/', f'"{BASE_PATH}/bank/'),
        ('"/reader"', f'"{BASE_PATH}/reader"'),
        ('"/reader/', f'"{BASE_PATH}/reader/'),
        
        # Single quotes
        ("'/assets/", f"'{BASE_PATH}/assets/"),
        ("'/bgm.mp3'", f"'{BASE_PATH}/bgm.mp3'"),
        ("'/favicon.ico'", f"'{BASE_PATH}/favicon.ico'"),
        ("'/cache/", f"'{BASE_PATH}/cache/"),
        ("'/bank/", f"'{BASE_PATH}/bank/"),
        ("'/reader'", f"'{BASE_PATH}/reader'"),
        ("'/reader/", f"'{BASE_PATH}/reader/"),
        
        # Backticks
        ('`/assets/', f'`{BASE_PATH}/assets/'),
        ('`/bgm.mp3`', f'`{BASE_PATH}/bgm.mp3`'),
        ('`/bgm.mp3`', f'`{BASE_PATH}/bgm.mp3`'), # both exact and slash variations
        ('`/favicon.ico`', f'`{BASE_PATH}/favicon.ico`'),
        ('`/cache/', f'`{BASE_PATH}/cache/'),
        ('`/bank/', f'`{BASE_PATH}/bank/'),
        ('`/reader`', f'`{BASE_PATH}/reader`'),
        ('`/reader/', f'`{BASE_PATH}/reader/'),

        # HTML / basename specific
        ('href="/assets/', f'href="{BASE_PATH}/assets/'),
        ('href="/favicon.ico"', f'href="{BASE_PATH}/favicon.ico"'),
        ('"basename":"/"', f'"basename":"{BASE_PATH}/"'),
        ('"basename": "/"', f'"basename": "{BASE_PATH}/"'),
    ]

    modified = False
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            modified = True

    if modified:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Patched: {file_path}")

def walk_and_patch(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in ('.html', '.js', '.css', '.json'):
                patch_file(os.path.join(root, file))

if __name__ == '__main__':
    target_dir = '.web/build/client'
    if not os.path.exists(target_dir):
        print(f"Error: {target_dir} does not exist!")
        sys.exit(1)

    print(f"Patching files for GitHub Pages subpath: {BASE_PATH}")
    walk_and_patch(target_dir)

    # Create .nojekyll
    nojekyll_path = os.path.join(target_dir, '.nojekyll')
    with open(nojekyll_path, 'w') as f:
        pass
    print("Created .nojekyll file to prevent Jekyll processing on GitHub Pages")
