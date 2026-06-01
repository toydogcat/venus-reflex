import json

def main():
    manifest_path = 'bank/小說/zhenhuanzhuan/manifest.json'
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    volumes = manifest.get('volumes', [])
    
    # Manually defined first chapters from checking the content earlier
    book_starts = [
        "第一章 雲意春深",
        "第一章 錦瑟",
        "第一章 歸來",
        "第一章 秋聲",
        "第一章 芳盟",
        "第一章 迷情",
        "第一章 故心"
    ]
    # But wait, looking at the previous grep, the text might be different
    # Let's look at page 162, 287, etc to be sure.
    # Actually, the manifest grep showed: "第一章 花落人亡兩不知", "第一章 雲意春深", etc.
    # Let's re-examine page 3 (start of Book I), and other book start pages.
    pass

if __name__ == "__main__":
    main()
