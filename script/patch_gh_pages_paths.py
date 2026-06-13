#!/usr/bin/env python3
import os
import sys
import re

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

    # Dynamic URL and connection toast patching
    if file_path.endswith('.js'):
        # 1. Patch getBackendURL function definition
        get_backend_url_pattern = r"getBackendURL\s*=\s*([a-zA-Z0-9_]+)\s*=>\s*\{\s*\(\1\?\?void\s*0\)===\s*void\s*0&&\s*\(\1\s*=\s*([a-zA-Z0-9_]+)\.PING\)\s*;\s*let\s+([a-zA-Z0-9_]+)\s*=\s*new\s+URL\(\1\)\s*;\s*return\s+typeof\s+window\s*<\s*`u`\s*&&\s*SAME_DOMAIN_HOSTNAMES\.includes\(\3\.hostname\)\s*&&\s*\(\3\.hostname\s*=\s*window\.location\.hostname\s*,\s*window\.location\.protocol\s*===\s*`https:`\s*&&\s*\(\3\.protocol\s*===\s*`ws:`\s*\?\s*\3\.protocol\s*=\s*`wss:`\s*:\s*\3\.protocol\s*===\s*`http:`\s*&&\s*\(\3\.protocol\s*=\s*`https:`\s*\)\s*,\s*\3\.port\s*=\s*``\s*\)\s*\)\s*,\s*\3\s*\}"
        match = re.search(get_backend_url_pattern, content)
        if match:
            arg_t = match.group(1)
            var_env = match.group(2)
            var_d = match.group(3)
            
            replacement = (
                f"getBackendURL = {arg_t} => {{"
                f"({arg_t} ?? void 0) === void 0 && ({arg_t} = {var_env}.PING);"
                f"if (typeof window < `u`) {{"
                f"  const params = new URLSearchParams(window.location.search);"
                f"  let custom = params.get(`api_url`) || localStorage.getItem(`reflex_api_url`);"
                f"  if (custom) {{"
                f"    localStorage.setItem(`reflex_api_url`, custom);"
                f"    custom.startsWith(`http://`) || custom.startsWith(`https://`) || (custom = (window.location.protocol === `https:` ? `https://` : `http://`) + custom);"
                f"    let {var_d} = new URL(custom);"
                f"    return window.location.protocol === `https:` && ![`localhost`, `127.0.0.1`].includes({var_d}.hostname) && ({var_d}.protocol === `ws:` ? {var_d}.protocol = `wss:` : {var_d}.protocol === `http:` && ({var_d}.protocol = `https:`)), {var_d};"
                f"  }}"
                f"}}"
                f"let {var_d} = new URL({arg_t});"
                f"return typeof window < `u` && SAME_DOMAIN_HOSTNAMES.includes({var_d}.hostname) && ({var_d}.hostname = window.location.hostname, window.location.protocol === `https:` && ({var_d}.protocol === `ws:` ? {var_d}.protocol = `wss:` : {var_d}.protocol === `http:` && ({var_d}.protocol = `https:`), {var_d}.port = ``)), {var_d}"
                f"}}"
            )
            content = content.replace(match.group(0), replacement)
            modified = True
            print(f"Patched getBackendURL in {file_path}")

        # 2. Patch connection error toast description
        toast_pattern = r"description\s*:\s*`Check if server is reachable at `\s*\+\s*([a-zA-Z0-9_]+)\(([a-zA-Z0-9_]+)\.EVENT\)\.href"
        if re.search(toast_pattern, content):
            content = re.sub(toast_pattern, r"description:`Check if server is reachable at `+\1(\2.EVENT).href+` or use ?api_url=<url> to set custom backend.`", content)
            modified = True
            print(f"Patched connection error toast description in {file_path}")

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
