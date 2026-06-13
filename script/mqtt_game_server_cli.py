#!/usr/bin/env python3
import os
import sys
import time
import hashlib
import json
import threading
import base64
import zipfile
import re
from pathlib import Path
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# 預設設定
ROOM_ID = "5S8A2"
PASSWORD = "pass123"
BROKER_HOST = "broker.emqx.io"
BROKER_PORT = 1883

# 全域狀態
mqtt_client = None
server_thread = None
is_running = False
logs = []
logs_lock = threading.Lock()
messages_received = 0

# 路徑設定
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BANK_DIR = PROJECT_ROOT / "bank"

# 自然排序函數
def natural_sort_key(s: str):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

# 轉換圖片檔案為 Base64 Data URL
def file_to_base64_data_url(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    mime_type = "image/jpeg"
    if suffix == ".png":
        mime_type = "image/png"
    elif suffix == ".webp":
        mime_type = "image/webp"
    elif suffix == ".gif":
        mime_type = "image/gif"
    
    try:
        with open(file_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
            return f"data:{mime_type};base64,{encoded}"
    except Exception as e:
        log_message(f"讀取圖片 {file_path} 失敗: {e}")
        return ""

# 轉換 ZIP 壓縮檔內的圖片為 Base64 Data URL
def zip_entry_to_base64_data_url(zip_path: Path, entry_name: str) -> str:
    suffix = Path(entry_name).suffix.lower()
    mime_type = "image/jpeg"
    if suffix == ".png":
        mime_type = "image/png"
    elif suffix == ".webp":
        mime_type = "image/webp"
    elif suffix == ".gif":
        mime_type = "image/gif"
        
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            with z.open(entry_name) as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
                return f"data:{mime_type};base64,{encoded}"
    except Exception as e:
        log_message(f"讀取壓縮檔項目 {entry_name} 失敗: {e}")
        return ""

# 載入本機書籍清單與分類排序 (對 Cover 做 Base64 轉換)
def _blocking_load_books() -> tuple[list, list]:
    books_list = []
    cat_order = []
    
    cat_file = BANK_DIR / "categories.json"
    if cat_file.exists():
        try:
            with open(cat_file, 'r', encoding='utf-8') as f:
                cat_data = json.load(f)
                cat_order = [c["name"] for c in sorted(cat_data, key=lambda x: x.get("order", 99))]
        except Exception as e:
            log_message(f"讀取分類檔失敗: {e}")
            
    if BANK_DIR.exists():
        # 掃描資料夾書籍
        for manifest_path in BANK_DIR.rglob("manifest.json"):
            if manifest_path.parent == BANK_DIR: continue
            book_dir = manifest_path.parent
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                    manifest["is_zip"] = False
                    manifest["rel_path"] = str(book_dir.relative_to(BANK_DIR))
                    
                    # 掃描頁面列表
                    pages_path = book_dir / "pages"
                    pages_list = []
                    if pages_path.exists():
                        pages_list = sorted([f.name for f in pages_path.glob("*.json")], key=natural_sort_key)
                    manifest["pages_list"] = pages_list
                    
                    # 尋找封面
                    cover_file = ""
                    if pages_path.exists():
                        first_page = pages_path / "0001.json"
                        if first_page.exists():
                            with open(first_page, 'r') as pf:
                                page_data = json.load(pf)
                                for el in page_data.get("elements", []):
                                    if el.get("type") == "image":
                                        cover_file = Path(el["src"]).name
                                        break
                    if not cover_file:
                        assets_path = book_dir / "assets"
                        if assets_path.exists():
                            all_imgs = sorted([img_f.name for img_f in assets_path.iterdir() if img_f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp')], key=natural_sort_key)
                            if all_imgs: cover_file = all_imgs[0]
                    
                    cover_path = book_dir / "assets" / cover_file
                    manifest["cover_src"] = file_to_base64_data_url(cover_path) if cover_file and cover_path.exists() else ""
                    books_list.append(manifest)
            except Exception as e:
                log_message(f"載入書籍失敗 {book_dir}: {e}")

        # 掃描 ZIP 壓縮書籍
        for zip_path in BANK_DIR.rglob("*.zip"):
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    manifest_name = next((n for n in z.namelist() if n.endswith('manifest.json')), None)
                    if not manifest_name: continue
                    
                    with z.open(manifest_name) as f:
                        manifest = json.loads(f.read().decode('utf-8'))
                        
                    manifest["is_zip"] = True
                    manifest["zip_path"] = str(zip_path)
                    manifest["zip_internal_prefix"] = str(Path(manifest_name).parent) if '/' in manifest_name else ""
                    manifest["rel_path"] = str(zip_path.relative_to(BANK_DIR))
                    
                    # 掃描頁面列表
                    prefix = manifest["zip_internal_prefix"]
                    pages_dir = os.path.join(prefix, "pages")
                    pages_list = sorted([Path(n).name for n in z.namelist() if n.startswith(pages_dir) and n.endswith('.json')], key=natural_sort_key)
                    manifest["pages_list"] = pages_list
                    
                    # 尋找封面
                    cover_internal_path = ""
                    first_page_name = next((n for n in z.namelist() if n.endswith('pages/0001.json')), None)
                    if first_page_name:
                        try:
                            with z.open(first_page_name) as pf:
                                page_data = json.loads(pf.read().decode('utf-8'))
                                for el in page_data.get("elements", []):
                                    if el.get("type") == "image":
                                        prefix = manifest["zip_internal_prefix"]
                                        cover_internal_path = os.path.normpath(os.path.join(prefix, el["src"])).lstrip('./')
                                        break
                        except: pass
                    
                    if not cover_internal_path:
                        try:
                            prefix = manifest["zip_internal_prefix"]
                            assets_prefix = os.path.join(prefix, "assets").lstrip('./')
                            img_entries = [n for n in z.namelist() if n.startswith(assets_prefix) and n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                            if img_entries:
                                cover_internal_path = sorted(img_entries, key=natural_sort_key)[0]
                        except: pass
                    
                    if cover_internal_path:
                        manifest["cover_src"] = zip_entry_to_base64_data_url(zip_path, cover_internal_path)
                    else:
                        manifest["cover_src"] = ""
                    books_list.append(manifest)
            except Exception as e:
                log_message(f"載入壓縮檔書籍失敗 {zip_path}: {e}")
                
    sorted_books = sorted(books_list, key=lambda x: natural_sort_key(x.get("title", "")))
    return sorted_books, cat_order

# 載入頁面並將頁面內所有圖片轉為 Base64 Data URL
def load_page_elements_base64(book: dict, page_file: str) -> list:
    elements = []
    try:
        if book.get("is_zip"):
            zip_path = Path(book["zip_path"])
            with zipfile.ZipFile(zip_path, 'r') as z:
                prefix = book["zip_internal_prefix"]
                internal_path = os.path.normpath(os.path.join(prefix, "pages", page_file)).lstrip('./')
                data = json.loads(z.read(internal_path).decode('utf-8'))
                elements = data.get("elements", [])
                
                namelist = set(z.namelist())
                
                for el in elements:
                    if el.get("type") == "image":
                        src = el.get("src", "")
                        img_internal_path = os.path.normpath(os.path.join(prefix, "pages", src)).lstrip('./')
                        if img_internal_path not in namelist:
                            img_internal_path = os.path.normpath(os.path.join(prefix, "assets", Path(src).name)).lstrip('./')
                        
                        el["src"] = zip_entry_to_base64_data_url(zip_path, img_internal_path)
        else:
            book_dir = BANK_DIR / book["rel_path"]
            page_path = book_dir / "pages" / page_file
            with open(page_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            elements = data.get("elements", [])
            
            for el in elements:
                if el.get("type") == "image":
                    src = el.get("src", "")
                    img_path = book_dir / "pages" / src
                    if not img_path.exists():
                        img_path = book_dir / "assets" / Path(src).name
                    
                    el["src"] = file_to_base64_data_url(img_path) if img_path.exists() else ""
    except Exception as e:
        log_message(f"讀取頁面失敗: {e}")
    
    return elements

# 金鑰與主題計算
def get_crypto_params(room_id, password):
    key = hashlib.sha256(password.encode('utf-8')).digest()
    topic_raw = f"{room_id.upper()}_{password}"
    topic_hash = hashlib.sha256(topic_raw.encode('utf-8')).hexdigest()[:16]
    c2s_topic = f"vreflex/rooms/{topic_hash}/c2s"
    s2c_topic = f"vreflex/rooms/{topic_hash}/s2c"
    return key, c2s_topic, s2c_topic

def log_message(text):
    with logs_lock:
        timestamp = time.strftime("%H:%M:%S")
        logs.append(f"[{timestamp}] {text}")
        if len(logs) > 100:
            logs.pop(0)

# 加密與解密函數
def encrypt_payload(data_dict, key):
    try:
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        plaintext = json.dumps(data_dict).encode('utf-8')
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext
    except Exception as e:
        log_message(f"加密失敗: {e}")
        return None

def decrypt_payload(payload, key):
    try:
        if len(payload) <= 12:
            return None
        aesgcm = AESGCM(key)
        nonce = payload[:12]
        ciphertext = payload[12:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode('utf-8'))
    except Exception:
        return None

# MQTT 回呼函數
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log_message("已成功連線至 MQTT Broker!")
        key, c2s_topic, s2c_topic = get_crypto_params(ROOM_ID, PASSWORD)
        client.subscribe(c2s_topic)
        log_message(f"已訂閱接收主題: {c2s_topic}")
    else:
        log_message(f"連線失敗，原因代碼: {reason_code}")

def on_disconnect(client, userdata, flags, reason_code, properties):
    log_message("已中斷與 MQTT Broker 的連線")

def on_message(client, userdata, msg):
    global messages_received
    messages_received += 1
    
    key, c2s_topic, s2c_topic = get_crypto_params(ROOM_ID, PASSWORD)
    decrypted = decrypt_payload(msg.payload, key)
    
    if decrypted:
        action = decrypted.get("action")
        req_id = decrypted.get("request_id")
        log_message(f"收到加密訊息 [解密成功]: action={action}, req_id={req_id}")
        
        if action == "ping":
            reply = {"action": "pong", "request_id": req_id, "sender": "PythonServer", "timestamp": time.time()}
            send_game_message(reply)
            
        elif action == "get_library":
            books, cat_order = _blocking_load_books()
            reply = {
                "action": "library_response",
                "request_id": req_id,
                "books": books,
                "category_order": cat_order
            }
            send_game_message(reply)
            
        elif action == "get_page":
            book_id = decrypted.get("book_id")
            page_file = decrypted.get("page_file")
            
            books, _ = _blocking_load_books()
            book = next((b for b in books if str(b.get("id")) == str(book_id)), None)
            
            elements = []
            if book:
                elements = load_page_elements_base64(book, page_file)
                
            reply = {
                "action": "page_response",
                "request_id": req_id,
                "page_elements": elements
            }
            send_game_message(reply)
            
        elif action == "submit_suggestion":
            suggestion = decrypted.get("suggestion")
            s_file = BANK_DIR / "suggestions.json"
            try:
                suggestions = []
                if s_file.exists():
                    with open(s_file, 'r', encoding='utf-8') as f:
                        suggestions = json.load(f)
                suggestions.append(suggestion)
                with open(s_file, 'w', encoding='utf-8') as f:
                    json.dump(suggestions, f, ensure_ascii=False, indent=2)
                log_message(f"已儲存建議至 suggestions.json: {suggestion}")
                reply = {"action": "suggestion_response", "request_id": req_id, "success": True}
            except Exception as e:
                log_message(f"儲存建議失敗: {e}")
                reply = {"action": "suggestion_response", "request_id": req_id, "success": False, "error": str(e)}
            send_game_message(reply)
    else:
        try:
            raw_text = msg.payload.decode('utf-8')
            log_message(f"收到未加密訊息 (可能是密碼不符): {raw_text}")
        except:
            log_message(f"收到無法解析的二進制訊息 (長度: {len(msg.payload)} bytes)")

# 發送/播送訊息給前端
def send_game_message(data_dict):
    global mqtt_client, is_running
    if not is_running or mqtt_client is None:
        log_message("無法發送：伺服器未啟動")
        return False
        
    key, c2s_topic, s2c_topic = get_crypto_params(ROOM_ID, PASSWORD)
    encrypted = encrypt_payload(data_dict, key)
    
    if encrypted:
        mqtt_client.publish(s2c_topic, encrypted)
        return True
    return False

# 啟動 MQTT 伺服器執行緒
def start_server():
    global mqtt_client, server_thread, is_running
    if is_running:
        log_message("伺服器已在運行中。")
        return
        
    is_running = True
    log_message(f"正在連線至 {BROKER_HOST}:{BROKER_PORT}...")
    
    mqtt_client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message
    
    mqtt_client.connect(BROKER_HOST, BROKER_PORT, 60)
    
    def loop_runner():
        while is_running:
            mqtt_client.loop(1.0)
        mqtt_client.disconnect()
        
    server_thread = threading.Thread(target=loop_runner, daemon=True)
    server_thread.start()

# 停止 MQTT 伺服器
def stop_server():
    global is_running, mqtt_client
    if not is_running:
        return
    is_running = False
    log_message("正在停止 MQTT 伺服器...")
    if server_thread:
        server_thread.join(timeout=2.0)
    log_message("伺服器已停止。")

# CLI 清理畫面
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# 輸出彩色橫幅
def print_banner():
    key, c2s, s2c = get_crypto_params(ROOM_ID, PASSWORD)
    print("\033[95m" + "="*60 + "\033[0m")
    print("\033[96m   🎮 VENUS READER - PRIVATE MQTT GAME SERVER (CLI) 🎮\033[0m")
    print("\033[95m" + "="*60 + "\033[0m")
    status = "\033[92m● 運行中 (ON)\033[0m" if is_running else "\033[91m○ 已停止 (OFF)\033[0m"
    print(f" 狀態: {status}    連線資訊: {BROKER_HOST}:{BROKER_PORT}")
    print(f" 房號 (Room ID): \033[93m{ROOM_ID}\033[0m      密碼 (Password): \033[93m{PASSWORD}\033[0m")
    print(f" 接收主題 (C2S): \033[90m{c2s}\033[0m")
    print(f" 發送主題 (S2C): \033[90m{s2c}\033[0m")
    print(f" 已處理訊息量: {messages_received}")
    print("\033[95m" + "="*60 + "\033[0m")

# 顯示日誌查看器
def view_logs():
    clear_screen()
    print("\033[96m--- 實時日誌監控 (按下 Enter 返回主選單) ---\033[0m")
    print("等待訊息中...\n")
    
    stop_event = threading.Event()
    
    def log_printer():
        last_len = 0
        while not stop_event.is_set():
            with logs_lock:
                current_len = len(logs)
                if current_len > last_len:
                    for i in range(last_len, current_len):
                        print(logs[i])
                    last_len = current_len
            time.sleep(0.2)
            
    printer_thread = threading.Thread(target=log_printer, daemon=True)
    printer_thread.start()
    
    input() # 等待使用者按下 Enter
    stop_event.set()
    printer_thread.join()

def main_menu():
    global ROOM_ID, PASSWORD, is_running
    while True:
        clear_screen()
        print_banner()
        print(" [1] 🛠️ 設定房間與密碼")
        print(" [2] ⚡ 啟動 MQTT 伺服器")
        print(" [3] 🔌 停止 MQTT 伺服器")
        print(" [4] 📑 查看實時通訊日誌 (監控器)")
        print(" [5] 💬 手動廣播測試訊息 (JSON)")
        print(" [6] ❌ 離開程式")
        print("\033[95m" + "="*60 + "\033[0m")
        
        choice = input("請選擇功能 [1-6]: ").strip()
        
        if choice == "1":
            new_room = input(f"請輸入新房號 (Enter 保留 '{ROOM_ID}'): ").strip()
            new_pass = input(f"請輸入新密碼 (Enter 保留 '{PASSWORD}'): ").strip()
            
            was_running = is_running
            if was_running:
                stop_server()
                
            if new_room:
                ROOM_ID = new_room.upper()
            if new_pass:
                PASSWORD = new_pass
                
            log_message(f"更新房間設定：房號={ROOM_ID}, 密碼={PASSWORD}")
            
            if was_running:
                start_server()
                
        elif choice == "2":
            if is_running:
                input("伺服器已在運行中。按 Enter 鍵返回...")
            else:
                start_server()
                time.sleep(0.5) # 等待連線日誌寫入
                
        elif choice == "3":
            if not is_running:
                input("伺服器本來就是停止的。按 Enter 鍵返回...")
            else:
                stop_server()
                input("伺服器已停止。按 Enter 鍵返回...")
                
        elif choice == "4":
            view_logs()
            
        elif choice == "5":
            if not is_running:
                input("請先啟動伺服器再發送訊息！按 Enter 鍵返回...")
                continue
            print("\n請輸入欲廣播的 JSON 訊息內容。範例: {\"action\": \"start_game\", \"cards\": [1,2,3]}")
            json_str = input("JSON 內容: ").strip()
            try:
                data = json.loads(json_str) if json_str else {"test": "hello"}
                success = send_game_message(data)
                if success:
                    print("發送成功！")
                time.sleep(1)
            except json.JSONDecodeError:
                print("\033[91m錯誤：輸入格式非合法的 JSON！\033[0m")
                time.sleep(1.5)
                
        elif choice == "6":
            if is_running:
                stop_server()
            print("\n感謝使用，再見！")
            break
        else:
            print("\033[91m無效選擇，請重新輸入！\033[0m")
            time.sleep(1)

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        if is_running:
            stop_server()
        print("\n程式被使用者中斷，已安全退出。")
        sys.exit(0)
