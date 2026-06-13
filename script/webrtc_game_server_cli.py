#!/usr/bin/env python3
import os
import sys
import time
import hashlib
import json
import asyncio
import threading
import base64
import zipfile
import re
from pathlib import Path
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from aiortc import RTCPeerConnection, RTCSessionDescription

# 預設設定
ROOM_ID = "5S8A2"
PASSWORD = "pass123"
BROKER_HOST = "broker.emqx.io"
BROKER_PORT = 1883

# 全域狀態
mqtt_client = None
loop_thread = None
event_loop = None
is_running = False
logs = []
logs_lock = threading.Lock()
messages_received = 0
active_pcs = set()

# 路徑設定
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BANK_DIR = PROJECT_ROOT / "bank"

def natural_sort_key(s: str):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

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
        # 資料夾書籍
        for manifest_path in BANK_DIR.rglob("manifest.json"):
            if manifest_path.parent == BANK_DIR: continue
            book_dir = manifest_path.parent
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                    manifest["is_zip"] = False
                    manifest["rel_path"] = str(book_dir.relative_to(BANK_DIR))
                    
                    # 頁面列表
                    pages_path = book_dir / "pages"
                    pages_list = []
                    if pages_path.exists():
                        pages_list = sorted([f.name for f in pages_path.glob("*.json")], key=natural_sort_key)
                    manifest["pages_list"] = pages_list
                    
                    # 封面
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

        # ZIP 壓縮書籍
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
                    
                    prefix = manifest["zip_internal_prefix"]
                    pages_dir = os.path.join(prefix, "pages")
                    pages_list = sorted([Path(n).name for n in z.namelist() if n.startswith(pages_dir) and n.endswith('.json')], key=natural_sort_key)
                    manifest["pages_list"] = pages_list
                    
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

# WebRTC 連線處理
async def handle_webrtc_connection(offer_sdp, client_id):
    try:
        key, c2s_topic, s2c_topic = get_crypto_params(ROOM_ID, PASSWORD)
        log_message(f"開始為用戶 {client_id} 建立 WebRTC P2P 連線...")
        
        pc = RTCPeerConnection()
        active_pcs.add(pc)
        
        @pc.on("datachannel")
        def on_datachannel(channel):
            log_message(f"WebRTC DataChannel '{channel.label}' 已順利接通!")
            
            @channel.on("message")
            def on_message(message):
                global messages_received
                messages_received += 1
                
                # 嘗試解密訊息
                try:
                    decrypted = decrypt_payload(message, key)
                except Exception as e:
                    log_message(f"DataChannel 訊息解密失敗: {e}")
                    import traceback
                    traceback.print_exc()
                    return
                    
                if not decrypted:
                    log_message("DataChannel 收到無效的加密資料包")
                    return
                    
                try:
                    action = decrypted.get("action")
                    req_id = decrypted.get("request_id")
                    log_message(f"DataChannel 收到請求: action={action}, req_id={req_id}")
                    
                    if action == "ping":
                        reply = {"action": "pong", "request_id": req_id, "sender": "PythonServer", "timestamp": time.time()}
                        send_reply(channel, reply)
                        
                    elif action == "get_library":
                        books, cat_order = _blocking_load_books()
                        # 複製並移除大體積的 cover_src，改為在前端懶加載以防 WebRTC Reassembly Queue 耗盡
                        books_light = []
                        for b in books:
                            b_copy = b.copy()
                            if "cover_src" in b_copy:
                                b_copy["cover_src"] = ""
                            books_light.append(b_copy)
                        reply = {
                            "action": "library_response",
                            "request_id": req_id,
                            "books": books_light,
                            "category_order": cat_order
                        }
                        send_reply(channel, reply)
                        
                    elif action == "get_cover":
                        book_id = decrypted.get("book_id")
                        books, _ = _blocking_load_books()
                        book = next((b for b in books if str(b.get("id")) == str(book_id)), None)
                        cover_src = book.get("cover_src", "") if book else ""
                        reply = {
                            "action": "cover_response",
                            "request_id": req_id,
                            "book_id": book_id,
                            "cover_src": cover_src
                        }
                        send_reply(channel, reply)
                        
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
                        send_reply(channel, reply)
                        
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
                        send_reply(channel, reply)
                except Exception as e:
                    log_message(f"處理 DataChannel 請求時發生錯誤: {e}")
                    import traceback
                    traceback.print_exc()

        @pc.on("connectionstatechange")
        def on_connectionstatechange():
            log_message(f"WebRTC 連線狀態變更: {pc.connectionState}")
            if pc.connectionState in ["failed", "closed"]:
                active_pcs.discard(pc)
                log_message(f"用戶 {client_id} 的 WebRTC 連線已斷開")

        # 設定遠端描述
        offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
        await pc.setRemoteDescription(offer)
        
        # 建立 Answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        
        # 等待 ICE 候選收集完成
        log_message("收集本機 ICE 候選中...")
        while pc.iceGatheringState != "complete":
            await asyncio.sleep(0.05)
            
        # 送出 Answer
        reply = {
            "type": "answer",
            "sdp": pc.localDescription.sdp,
            "client_id": client_id,
            "sender": "PythonServer"
        }
        encrypted = encrypt_payload(reply, key)
        if encrypted:
            mqtt_client.publish(s2c_topic, encrypted)
            log_message(f"已回傳 WebRTC SDP Answer 至 {s2c_topic}")
    except Exception as e:
        log_message(f"建立 WebRTC 連線時發生崩潰: {e}")
        import traceback
        traceback.print_exc()

def send_reply(channel, data_dict):
    try:
        key, _, _ = get_crypto_params(ROOM_ID, PASSWORD)
        encrypted = encrypt_payload(data_dict, key)
        if encrypted:
            channel.send(encrypted)
    except Exception as e:
        log_message(f"發送 DataChannel 響應時失敗: {e}")
        import traceback
        traceback.print_exc()

# MQTT 回呼函數 (信令)
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log_message("信令連線成功：已連接至 MQTT Broker!")
        key, c2s_topic, s2c_topic = get_crypto_params(ROOM_ID, PASSWORD)
        client.subscribe(c2s_topic)
        log_message(f"已訂閱信令接收主題: {c2s_topic}")
    else:
        log_message(f"信令連線失敗，原因代碼: {reason_code}")

def on_message(client, userdata, msg):
    try:
        key, c2s_topic, s2c_topic = get_crypto_params(ROOM_ID, PASSWORD)
        decrypted = decrypt_payload(msg.payload, key)
        
        if decrypted:
            msg_type = decrypted.get("type")
            client_id = decrypted.get("client_id")
            
            if msg_type == "offer":
                sdp = decrypted.get("sdp")
                future = asyncio.run_coroutine_threadsafe(
                    handle_webrtc_connection(sdp, client_id),
                    event_loop
                )
                def done_callback(f):
                    try:
                        f.result()
                    except Exception as ex:
                        log_message(f"WebRTC 任務執行發生未捕獲異常: {ex}")
                future.add_done_callback(done_callback)
        else:
            try:
                raw_text = msg.payload.decode('utf-8')
                log_message(f"收到未加密訊息 (密碼不符): {raw_text}")
            except:
                pass
    except Exception as e:
        log_message(f"處理信令訊息時出錯: {e}")
        import traceback
        traceback.print_exc()

def start_server():
    global mqtt_client, loop_thread, event_loop, is_running
    if is_running:
        return
        
    is_running = True
    event_loop = asyncio.new_event_loop()
    
    log_message(f"正在連線至信令伺服器 {BROKER_HOST}:{BROKER_PORT}...")
    mqtt_client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    
    mqtt_client.connect(BROKER_HOST, BROKER_PORT, 60)
    mqtt_client.loop_start()
    
    def loop_runner():
        asyncio.set_event_loop(event_loop)
        event_loop.run_forever()
        
    loop_thread = threading.Thread(target=loop_runner, daemon=True)
    loop_thread.start()

def stop_server():
    global is_running, mqtt_client, event_loop
    if not is_running:
        return
    is_running = False
    log_message("正在關閉連線中...")
    
    # 關閉所有 WebRTC PCs
    for pc in list(active_pcs):
        asyncio.run_coroutine_threadsafe(pc.close(), event_loop)
    active_pcs.clear()
    
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        
    if event_loop:
        event_loop.call_soon_threadsafe(event_loop.stop)
        
    log_message("伺服器已停止。")

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    key, c2s, s2c = get_crypto_params(ROOM_ID, PASSWORD)
    print("\033[95m" + "="*60 + "\033[0m")
    print("\033[96m   🎮 VENUS READER - P2P WEBRTC GAME SERVER (CLI) 🎮\033[0m")
    print("\033[95m" + "="*60 + "\033[0m")
    status = "\033[92m● 運行中 (ON)\033[0m" if is_running else "\033[91m○ 已停止 (OFF)\033[0m"
    print(f" 狀態: {status}    信令代理: {BROKER_HOST}:{BROKER_PORT}")
    print(f" 房號 (Room ID): \033[93m{ROOM_ID}\033[0m      密碼 (Password): \033[93m{PASSWORD}\033[0m")
    print(f" 信令接收 (C2S): \033[90m{c2s}\033[0m")
    print(f" 信令發送 (S2C): \033[90m{s2c}\033[0m")
    print(f" 已連線用戶數: {len(active_pcs)}")
    print("\033[95m" + "="*60 + "\033[0m")

def view_logs():
    clear_screen()
    print("\033[96m--- 實時日誌監控 (按下 Enter 返回主選單) ---\033[0m")
    print("等待通訊中...\n")
    
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
    
    input()
    stop_event.set()
    printer_thread.join()

def main_menu():
    global ROOM_ID, PASSWORD, is_running
    while True:
        clear_screen()
        print_banner()
        print(" [1] 🛠️ 設定房間與密碼")
        print(" [2] ⚡ 啟動 WebRTC 信令伺服器")
        print(" [3] 🔌 停止 WebRTC 伺服器")
        print(" [4] 📑 查看實時連線日誌 (監控器)")
        print(" [5] ❌ 離開程式")
        print("\033[95m" + "="*60 + "\033[0m")
        
        choice = input("請選擇功能 [1-5]: ").strip()
        
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
                time.sleep(0.5)
                
        elif choice == "3":
            if not is_running:
                input("伺服器為停止狀態。按 Enter 鍵返回...")
            else:
                stop_server()
                input("伺服器已停止。按 Enter 鍵返回...")
                
        elif choice == "4":
            view_logs()
            
        elif choice == "5":
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
        sys.exit(0)
