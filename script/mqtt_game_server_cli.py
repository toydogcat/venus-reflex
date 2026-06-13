#!/usr/bin/env python3
import os
import sys
import time
import hashlib
import json
import threading
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

# 金鑰與主題計算
def get_crypto_params(room_id, password):
    # 用密碼做 SHA-256 產生 32-byte (256-bit) AES 金鑰
    key = hashlib.sha256(password.encode('utf-8')).digest()
    
    # 用房號 + 密碼產生 Topic 的 Hash，防外人窺探主題
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
    except Exception as e:
        # 解密失敗通常表示密碼錯誤或是未加密的垃圾資料
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
    
    # 嘗試用當前密碼解密
    decrypted = decrypt_payload(msg.payload, key)
    
    if decrypted:
        log_message(f"收到加密訊息 [解密成功]: {decrypted}")
        # 在此處可以加入自動遊戲邏輯回覆
        # 範例：若收到 {action: ping}，自動回覆 {action: pong}
        if decrypted.get("action") == "ping":
            reply = {"action": "pong", "sender": "PythonServer", "timestamp": time.time()}
            send_game_message(reply)
    else:
        # 嘗試以純文字解碼 (未加密的資料)
        try:
            raw_text = msg.payload.decode('utf-8')
            log_message(f"收到未加密訊息 (可能是密碼不符或測試訊息): {raw_text}")
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
        log_message(f"已廣播加密訊息至 {s2c_topic}: {data_dict}")
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
    
    # 使用 paho-mqtt v2.x.x
    mqtt_client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message
    
    # 設定連線參數
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
