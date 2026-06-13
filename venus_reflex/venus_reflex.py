import reflex as rx
import json
import re
import zipfile
import io
import os
from pathlib import Path
from typing import Any, List, Dict, Optional, Set
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi.responses import Response
from starlette.requests import Request
from rxconfig import config
import hashlib
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BANK_DIR = PROJECT_ROOT / "bank"
SUGGESTIONS_FILE = PROJECT_ROOT / "suggestions.json"
CACHE_DIR = PROJECT_ROOT / "assets" / "cache"

# Ensure cache dir exists for covers
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Thread-safe global caches and executors
_library_cache: List[Dict[str, Any]] = []
_category_cache: List[str] = []
_library_cache_lock = threading.Lock()
_io_executor = ThreadPoolExecutor(max_workers=4)
_suggestion_lock = asyncio.Lock()

def natural_sort_key(s: str):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def _blocking_load_books() -> tuple[List[Dict[str, Any]], List[str]]:
    books_list = []
    cat_order = []
    
    # 1. Load category order
    cat_file = BANK_DIR / "categories.json"
    if cat_file.exists():
        try:
            with open(cat_file, 'r', encoding='utf-8') as f:
                cat_data = json.load(f)
                cat_order = [c["name"] for c in sorted(cat_data, key=lambda x: x.get("order", 99))]
        except Exception as e:
            print(f"Error loading categories: {e}")
    
    # 2. Recursively scan bank/
    if BANK_DIR.exists():
        # Scan for manifest.json (Directories)
        for manifest_path in BANK_DIR.rglob("manifest.json"):
            if manifest_path.parent == BANK_DIR: continue
            book_dir = manifest_path.parent
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                    manifest["is_zip"] = False
                    manifest["rel_path"] = str(book_dir.relative_to(BANK_DIR))
                    
                    # Find cover
                    cover_file = ""
                    pages_path = book_dir / "pages"
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
                    
                    manifest["cover_src"] = f"/bank/{manifest['rel_path']}/assets/{cover_file}" if cover_file else ""
                    books_list.append(manifest)
            except Exception as e:
                print(f"Error loading book at {book_dir}: {e}")

        # Scan for .zip files (Archives)
        for zip_path in BANK_DIR.rglob("*.zip"):
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    # Try to find manifest.json inside zip
                    manifest_name = next((n for n in z.namelist() if n.endswith('manifest.json')), None)
                    if not manifest_name: continue
                    
                    with z.open(manifest_name) as f:
                        manifest = json.loads(f.read().decode('utf-8'))
                        
                    manifest["is_zip"] = True
                    manifest["zip_path"] = str(zip_path)
                    # Root prefix should be empty string, not "."
                    manifest["zip_internal_prefix"] = str(Path(manifest_name).parent) if '/' in manifest_name else ""
                    manifest["rel_path"] = str(zip_path.relative_to(BANK_DIR))
                    
                    # Handle cover for ZIP
                    book_id = manifest["id"]
                    cover_cache_name = f"cover_{book_id}.webp"
                    cover_cache_path = CACHE_DIR / cover_cache_name
                    
                    if not cover_cache_path.exists():
                        # Extract cover from first page
                        first_page_name = next((n for n in z.namelist() if n.endswith('pages/0001.json')), None)
                        cover_internal_path = ""
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
                            # Fallback to first image in assets
                            try:
                                prefix = manifest["zip_internal_prefix"]
                                assets_prefix = os.path.join(prefix, "assets").lstrip('./')
                                img_entries = [n for n in z.namelist() if n.startswith(assets_prefix) and n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                                if img_entries:
                                    cover_internal_path = sorted(img_entries, key=natural_sort_key)[0]
                            except: pass
                        
                        if cover_internal_path:
                            try:
                                with z.open(cover_internal_path) as src, open(cover_cache_path, 'wb') as dst:
                                    dst.write(src.read())
                            except: pass
                    
                    manifest["cover_src"] = f"/cache/{cover_cache_name}" if cover_cache_path.exists() else ""
                    books_list.append(manifest)
            except Exception as e:
                print(f"Error loading zip at {zip_path}: {e}")
    
    sorted_books = sorted(books_list, key=lambda x: natural_sort_key(x.get("title", "")))
    return sorted_books, cat_order

class State(rx.State):
    all_books: List[Dict[str, Any]] = []
    category_order: List[str] = []
    search_query: str = ""
    expanded_categories: Set[str] = set()
    expanded_subcategories: Set[str] = set()
    
    # Login & MQTT connection state
    is_logged_in: bool = False
    is_mqtt_mode: bool = False
    room_id_input: str = ""
    password_input: str = ""
    connection_status: str = ""
    is_connecting: bool = False
    
    # Private MQTT fields (not synchronized to client)
    _mqtt_client: Any = None
    _mqtt_key: bytes = b""
    _mqtt_c2s: str = ""
    _mqtt_s2c: str = ""
    _mqtt_futures: Dict[str, Any] = {}
    
    # ... (skipping unchanged Reader/BGM/Volume state vars)
    selected_book_id: str = ""
    current_book_info: Dict[str, Any] = {}
    pages_list: List[str] = []
    current_page_idx: int = 0
    
    # Reader State
    page_elements_left: List[Dict[str, Any]] = []
    page_elements_right: List[Dict[str, Any]] = []
    is_dual_mode: bool = False
    novel_font_size: int = 24
    suggestion_text: str = ""
    jump_page_input: str = ""
    
    # BGM State
    is_playing_bgm: bool = False
    bgm_volume: float = 0.5

    # Nested Volume State
    selected_volume_index: int = -1
    volume_search_query: str = ""

    async def _send_mqtt_request(self, action: str, payload: dict, expected_response_action: str, timeout: float = 8.0) -> Optional[dict]:
        if not self._mqtt_client or not self._mqtt_key:
            return None
            
        req_id = os.urandom(8).hex()
        payload["action"] = action
        payload["request_id"] = req_id
        
        # Encrypt the payload
        aesgcm = AESGCM(self._mqtt_key)
        nonce = os.urandom(12)
        plaintext = json.dumps(payload).encode('utf-8')
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        encrypted = nonce + ciphertext
        
        # Register future
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        
        self._mqtt_futures[req_id] = fut
        
        try:
            # Publish request
            self._mqtt_client.publish(self._mqtt_c2s, encrypted)
            
            # Wait for future with timeout
            response = await asyncio.wait_for(fut, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            print(f"MQTT request {action} timed out.")
            return None
        finally:
            if req_id in self._mqtt_futures:
                del self._mqtt_futures[req_id]

    def _on_mqtt_message(self, client, userdata, msg):
        if not self._mqtt_key:
            return
            
        payload = msg.payload
        if len(payload) <= 12:
            return
            
        try:
            aesgcm = AESGCM(self._mqtt_key)
            nonce = payload[:12]
            ciphertext = payload[12:]
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            decrypted = json.loads(plaintext.decode('utf-8'))
            
            req_id = decrypted.get("request_id")
            if req_id and req_id in self._mqtt_futures:
                fut = self._mqtt_futures[req_id]
                loop = fut.get_loop()
                if not fut.done():
                    loop.call_soon_threadsafe(fut.set_result, decrypted)
        except Exception as e:
            print(f"Error decrypting incoming message: {e}")

    async def connect_to_mqtt_server(self):
        room = self.room_id_input.strip().upper()
        password = self.password_input.strip()
        
        if not room or not password:
            self.connection_status = "Please enter both Room ID and Password."
            return
            
        self.is_connecting = True
        self.connection_status = f"Connecting to Room {room}..."
        yield # Force UI update
        
        # Calculate key and topics
        key = hashlib.sha256(password.encode('utf-8')).digest()
        topic_raw = f"{room}_{password}"
        topic_hash = hashlib.sha256(topic_raw.encode('utf-8')).hexdigest()[:16]
        c2s_topic = f"vreflex/rooms/{topic_hash}/c2s"
        s2c_topic = f"vreflex/rooms/{topic_hash}/s2c"
        
        try:
            # Initialize MQTT client
            client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
            client.on_message = self._on_mqtt_message
            
            loop = asyncio.get_running_loop()
            conn_future = loop.create_future()
            
            def on_connect(client, userdata, flags, reason_code, properties):
                if reason_code == 0:
                    loop.call_soon_threadsafe(conn_future.set_result, True)
                else:
                    loop.call_soon_threadsafe(conn_future.set_result, Exception(f"Connection failed with code {reason_code}"))
                    
            client.on_connect = on_connect
            
            # Connect synchronously in executor thread
            await loop.run_in_executor(
                None,
                lambda: client.connect("broker.emqx.io", 1883, 60)
            )
            
            client.loop_start()
            
            # Wait for connection success with timeout
            try:
                await asyncio.wait_for(conn_future, timeout=5.0)
                client.subscribe(s2c_topic)
                
                self._mqtt_client = client
                self._mqtt_key = key
                self._mqtt_c2s = c2s_topic
                self._mqtt_s2c = s2c_topic
                
                self.connection_status = "Fetching library catalog..."
                yield
                
                # Fetch books library
                resp = await self._send_mqtt_request("get_library", {}, "library_response", timeout=6.0)
                if resp and resp.get("action") == "library_response":
                    self.all_books = resp.get("books", [])
                    self.category_order = resp.get("category_order", [])
                    self.is_logged_in = True
                    self.is_mqtt_mode = True
                    self.connection_status = ""
                else:
                    client.loop_stop()
                    client.disconnect()
                    self.connection_status = "Server timeout. Make sure the Python CLI server is running."
            except asyncio.TimeoutError:
                client.loop_stop()
                client.disconnect()
                self.connection_status = "Connection timeout. Please check your room or password."
            except Exception as e:
                client.loop_stop()
                client.disconnect()
                self.connection_status = f"Connection error: {e}"
        except Exception as e:
            self.connection_status = f"Failed to connect: {e}"
        finally:
            self.is_connecting = False

    async def enter_local_mode(self):
        self.is_logged_in = True
        self.is_mqtt_mode = False
        self.connection_status = ""
        await self.load_books()

    def logout(self):
        if self._mqtt_client:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except:
                pass
        self._mqtt_client = None
        self._mqtt_key = b""
        self._mqtt_c2s = ""
        self._mqtt_s2c = ""
        self._mqtt_futures.clear()
        self.is_logged_in = False
        self.is_mqtt_mode = False
        self.room_id_input = ""
        self.password_input = ""
        self.all_books = []
        self.category_order = []

    async def load_books(self):
        if not self.is_logged_in:
            return
        if self.is_mqtt_mode:
            resp = await self._send_mqtt_request("get_library", {}, "library_response")
            if resp and resp.get("action") == "library_response":
                self.all_books = resp.get("books", [])
                self.category_order = resp.get("category_order", [])
            return

        global _library_cache, _category_cache
        with _library_cache_lock:
            if _library_cache:
                self.all_books = _library_cache
                self.category_order = _category_cache
                return
        
        loop = asyncio.get_running_loop()
        books, cat_order = await loop.run_in_executor(_io_executor, _blocking_load_books)
        
        with _library_cache_lock:
            _library_cache = books
            _category_cache = cat_order
            self.all_books = _library_cache
            self.category_order = _category_cache

    @rx.var
    def filtered_categories(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        result = {}
        query = self.search_query.lower()
        for book in self.all_books:
            title = book.get("title", "").lower()
            author = book.get("author", "").lower()
            category = book.get("category", "未分類")
            subcategory = book.get("subcategory", "")
            
            if query in title or query in author or query.lower() in category.lower() or query.lower() in subcategory.lower():
                if category not in result: result[category] = {}
                if subcategory not in result[category]: result[category][subcategory] = []
                result[category][subcategory].append(book)
        
        # Sort books within each subcategory
        for cat in result:
            for sub in result[cat]:
                result[cat][sub] = sorted(result[cat][sub], key=lambda x: natural_sort_key(x.get("title", "")))
        
        # Final sorted result by category order
        sorted_result = {}
        for cat_name in self.category_order:
            if cat_name in result: sorted_result[cat_name] = result[cat_name]
        for cat_name in sorted(result.keys(), key=natural_sort_key):
            if cat_name not in sorted_result: sorted_result[cat_name] = result[cat_name]
            
        return sorted_result

    def toggle_category(self, cat_name: str):
        if cat_name in self.expanded_categories: self.expanded_categories.remove(cat_name)
        else: self.expanded_categories.add(cat_name)

    def toggle_subcategory(self, cat_sub: str):
        if cat_sub in self.expanded_subcategories: self.expanded_subcategories.remove(cat_sub)
        else: self.expanded_subcategories.add(cat_sub)

    def set_search_query(self, query: str):
        self.search_query = query
        if query:
            for cat, subs in self.filtered_categories.items():
                self.expanded_categories.add(cat)
                for sub in subs.keys():
                    self.expanded_subcategories.add(f"{cat}/{sub}")

    async def select_book(self, book_id: str):
        book = next((b for b in self.all_books if b["id"] == book_id), None)
        if not book: 
            print(f"Book ID {book_id} not found in all_books")
            return
        self.selected_book_id = book_id
        self.current_book_info = book
        print(f"Selecting book: {book.get('title')}, is_zip: {book.get('is_zip')}")
        
        if self.is_mqtt_mode:
            self.pages_list = book.get("pages_list", [])
        else:
            loop = asyncio.get_running_loop()
            if book.get("is_zip"):
                def _list_zip_pages():
                    with zipfile.ZipFile(book["zip_path"], 'r') as z:
                        prefix = book["zip_internal_prefix"]
                        pages_dir = os.path.join(prefix, "pages")
                        return sorted([Path(n).name for n in z.namelist() if n.startswith(pages_dir) and n.endswith('.json')], key=natural_sort_key)
                self.pages_list = await loop.run_in_executor(_io_executor, _list_zip_pages)
            else:
                book_path = BANK_DIR / book["rel_path"]
                pages_dir = book_path / "pages"
                if pages_dir.exists():
                    def _list_pages():
                        return sorted([f.name for f in pages_dir.glob("*.json")], key=natural_sort_key)
                    self.pages_list = await loop.run_in_executor(_io_executor, _list_pages)
                else:
                    self.pages_list = []
                    print(f"Pages directory not found: {pages_dir}")
        
        self.current_page_idx = 0
        self.selected_volume_index = -1
        self.volume_search_query = ""
        print(f"Found {len(self.pages_list)} pages")
        await self.load_current_page()
        return rx.redirect("/reader")

    async def _load_page_json(self, idx: int) -> List[Dict[str, Any]]:
        if 0 <= idx < len(self.pages_list):
            page_file = self.pages_list[idx]
            
            if self.is_mqtt_mode:
                resp = await self._send_mqtt_request(
                    "get_page",
                    {"book_id": self.current_book_info.get("id"), "page_file": page_file},
                    "page_response"
                )
                if resp and resp.get("action") == "page_response":
                    return resp.get("page_elements", [])
                return []
                
            loop = asyncio.get_running_loop()
            try:
                if self.current_book_info.get("is_zip"):
                    def _read_zip():
                        with zipfile.ZipFile(self.current_book_info["zip_path"], 'r') as z:
                            prefix = self.current_book_info["zip_internal_prefix"]
                            internal_path = os.path.normpath(os.path.join(prefix, "pages", page_file))
                            return json.loads(z.read(internal_path).decode('utf-8'))
                    data = await loop.run_in_executor(_io_executor, _read_zip)
                else:
                    page_path = BANK_DIR / self.current_book_info["rel_path"] / "pages" / page_file
                    def _read_file():
                        with open(page_path, 'r', encoding='utf-8') as f:
                            return json.load(f)
                    data = await loop.run_in_executor(_io_executor, _read_file)
                
                elements = data.get("elements", [])
                print(f"Loaded page {idx} ({page_file}): {len(elements)} elements")
                return elements
            except Exception as e:
                print(f"Error loading page json: {e}")
        return []

    async def load_current_page(self):
        if not self.selected_book_id or not self.pages_list:
            self.page_elements_left = []
            self.page_elements_right = []
            return
        self.page_elements_left = await self._load_page_json(self.current_page_idx)
        if self.is_dual_mode:
            self.page_elements_right = await self._load_page_json(self.current_page_idx + 1)
        else:
            self.page_elements_right = []
        self.suggestion_text = ""
        self.jump_page_input = ""
        return rx.scroll_to("reading-start")

    async def toggle_reading_mode(self):
        self.is_dual_mode = not self.is_dual_mode
        await self.load_current_page()

    def set_novel_font_size(self, size: list[float]):
        self.novel_font_size = int(size[0])

    async def select_volume(self, volume_idx: int):
        self.selected_volume_index = volume_idx
        volumes = self.current_book_info.get("volumes", [])
        if 0 <= volume_idx < len(volumes):
            vol = volumes[volume_idx]
            self.current_page_idx = vol["start_page"] - 1
            await self.load_current_page()

    async def exit_volume(self):
        self.selected_volume_index = -1

    def set_volume_search_query(self, query: str):
        self.volume_search_query = query

    @rx.var
    def active_volume_info(self) -> Dict[str, Any]:
        volumes = self.current_book_info.get("volumes", [])
        if self.selected_volume_index != -1 and 0 <= self.selected_volume_index < len(volumes):
            vol = volumes[self.selected_volume_index]
            return {
                "active": True,
                "title": vol["title"],
                "start_idx": vol["start_page"] - 1,
                "end_idx": vol["end_page"] - 1,
                "total_pages": vol["end_page"] - vol["start_page"] + 1,
                "relative_idx": self.current_page_idx - vol["start_page"] + 2
            }
        return {
            "active": False,
            "title": "",
            "start_idx": 0,
            "end_idx": max(0, len(self.pages_list) - 1),
            "total_pages": len(self.pages_list),
            "relative_idx": self.current_page_idx + 1
        }

    @rx.var
    def filtered_volumes(self) -> List[Dict[str, Any]]:
        volumes = self.current_book_info.get("volumes", [])
        if not volumes: return []
        query = self.volume_search_query.strip().lower()
        if not query:
            return [{"title": v["title"], "start_page": v["start_page"], "end_page": v["end_page"], "index": idx} for idx, v in enumerate(volumes)]
        
        filtered = []
        for idx, v in enumerate(volumes):
            if query in v["title"].lower():
                filtered.append({"title": v["title"], "start_page": v["start_page"], "end_page": v["end_page"], "index": idx})
        return filtered

    async def next_page(self):
        step = 2 if self.is_dual_mode else 1
        info = self.active_volume_info
        max_idx = info["end_idx"]
        if self.current_page_idx + step <= max_idx:
            self.current_page_idx += step
            return await self.load_current_page()
        elif self.is_dual_mode and self.current_page_idx + 1 <= max_idx:
             self.current_page_idx += 1
             return await self.load_current_page()

    async def prev_page(self):
        step = 2 if self.is_dual_mode else 1
        info = self.active_volume_info
        min_idx = info["start_idx"]
        if self.current_page_idx - step >= min_idx:
            self.current_page_idx -= step
        else:
            self.current_page_idx = min_idx
        return await self.load_current_page()

    async def next_volume(self):
        volumes = self.current_book_info.get("volumes", [])
        if self.selected_volume_index != -1 and volumes:
            if self.selected_volume_index + 1 < len(volumes):
                await self.select_volume(self.selected_volume_index + 1)
        else:
            cat = self.current_book_info.get("category", "未分類")
            cat_books = [b for b in self.all_books if b.get("category", "未分類") == cat]
            current_idx = next((i for i, b in enumerate(cat_books) if b["id"] == self.selected_book_id), -1)
            if current_idx != -1 and current_idx + 1 < len(cat_books):
                return await self.select_book(cat_books[current_idx + 1]["id"])

    async def prev_volume(self):
        volumes = self.current_book_info.get("volumes", [])
        if self.selected_volume_index != -1 and volumes:
            if self.selected_volume_index > 0:
                await self.select_volume(self.selected_volume_index - 1)
        else:
            cat = self.current_book_info.get("category", "未分類")
            cat_books = [b for b in self.all_books if b.get("category", "未分類") == cat]
            current_idx = next((i for i, b in enumerate(cat_books) if b["id"] == self.selected_book_id), -1)
            if current_idx > 0:
                return await self.select_book(cat_books[current_idx - 1]["id"])

    def set_suggestion_text(self, text: str):
        self.suggestion_text = text

    def set_room_id_input(self, val: str):
        self.room_id_input = val

    def set_password_input(self, val: str):
        self.password_input = val

    def set_jump_page_input(self, val: str):
        self.jump_page_input = val

    async def jump_to_page(self):
        try:
            target_page = int(self.jump_page_input)
            info = self.active_volume_info
            if 1 <= target_page <= info["total_pages"]:
                self.current_page_idx = info["start_idx"] + target_page - 1
                return await self.load_current_page()
            else:
                return rx.toast(f"Invalid page number. Max: {info['total_pages']}")
        except ValueError:
            return rx.toast("Please enter a valid number.")

    async def submit_suggestion(self):
        if not self.selected_book_id or not self.pages_list: return
        suggestion = {"book_id": self.selected_book_id, "book_title": self.current_book_info.get("title"), "page_index": self.current_page_idx, "page_file": self.pages_list[self.current_page_idx], "suggestion": self.suggestion_text}
        
        if self.is_mqtt_mode:
            resp = await self._send_mqtt_request(
                "submit_suggestion",
                {"suggestion": suggestion},
                "suggestion_response"
            )
            if resp and resp.get("success"):
                self.suggestion_text = ""
                return rx.toast("Suggestion saved to remote server!")
            else:
                return rx.toast("Failed to save suggestion to remote server.")
                
        async with _suggestion_lock:
            suggestions = []
            if SUGGESTIONS_FILE.exists():
                try:
                    loop = asyncio.get_running_loop()
                    def _read():
                        with open(SUGGESTIONS_FILE, 'r', encoding='utf-8') as f:
                            return json.load(f)
                    suggestions = await loop.run_in_executor(_io_executor, _read)
                except Exception as e:
                    print(f"Error reading suggestions: {e}")
            suggestions.append(suggestion)
            try:
                loop = asyncio.get_running_loop()
                def _write():
                    with open(SUGGESTIONS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(suggestions, f, ensure_ascii=False, indent=4)
                await loop.run_in_executor(_io_executor, _write)
            except Exception as e:
                print(f"Error writing suggestions: {e}")
                return rx.toast("Failed to save suggestion.")
                
        self.suggestion_text = ""
        return rx.toast("Suggestion saved!")

    def toggle_bgm(self):
        self.is_playing_bgm = not self.is_playing_bgm

    def set_bgm_volume(self, volume: list[float]):
        self.bgm_volume = float(volume[0] / 100.0)

    def go_back_to_library(self):
        return rx.redirect("/")

    @rx.var
    def bgm_volume_percent(self) -> str:
        return f"{int(self.bgm_volume * 100)}%"

    @rx.var
    def page_display_text(self) -> str:
        info = self.active_volume_info
        rel_idx = info["relative_idx"]
        total = info["total_pages"]
        if self.is_dual_mode:
            end_idx = min(rel_idx + 1, total)
            return f"Pages {rel_idx}-{end_idx} / {total}"
        return f"Page {rel_idx} / {total}"

    @rx.var
    def has_prev_volume(self) -> bool:
        volumes = self.current_book_info.get("volumes", [])
        if self.selected_volume_index != -1 and volumes:
            return self.selected_volume_index > 0
        cat = self.current_book_info.get("category", "未分類")
        cat_books = [b for b in self.all_books if b.get("category", "未分類") == cat]
        current_idx = next((i for i, b in enumerate(cat_books) if b["id"] == self.selected_book_id), -1)
        return current_idx > 0

    @rx.var
    def has_next_volume(self) -> bool:
        volumes = self.current_book_info.get("volumes", [])
        if self.selected_volume_index != -1 and volumes:
            return self.selected_volume_index + 1 < len(volumes)
        cat = self.current_book_info.get("category", "未分類")
        cat_books = [b for b in self.all_books if b.get("category", "未分類") == cat]
        current_idx = next((i for i, b in enumerate(cat_books) if b["id"] == self.selected_book_id), -1)
        return current_idx != -1 and current_idx + 1 < len(cat_books)

    @rx.var
    def current_book_volumes_count(self) -> int:
        volumes = self.current_book_info.get("volumes", [])
        return len(volumes) if volumes else 0

    @rx.var
    def has_volumes(self) -> bool:
        return bool(self.current_book_info.get("volumes"))

def render_element(el: Any, book_info: Any, novel_font_size: Any) -> rx.Component:
    # Resolve image path based on whether it's a zip or directory
    
    # Use full API URL for ZIP assets to bypass frontend proxy issues
    api_base = getattr(config, "api_url", "http://localhost:8003")
    
    zip_img_src = (
        rx.Var.create(f"{api_base}/api/zip_asset/") 
        + book_info["id"].to(str) 
        + "/" 
        + el["src"].to(str).replace("assets/", "")
    )
    
    dir_img_src = (
        rx.Var.create("/bank/") 
        + book_info["rel_path"].to(str) 
        + "/" 
        + el["src"].to(str)
    )

    img_src = rx.cond(
        el["src"].to(str).startswith("data:"),
        el["src"].to(str),
        rx.cond(
            book_info["is_zip"],
            zip_img_src,
            dir_img_src
        )
    )
    
    return rx.match(
        el["type"],
        ("image", rx.image(
            src=img_src,
            width="100%", height="auto", object_fit="contain", user_select="none", pointer_events="none"
        )),
        ("text", rx.box(
            rx.text(
                el["content"],
                font_size=rx.cond(
                    el["font_size"],
                    (el["font_size"].to(float) * novel_font_size / 24.0).to(str) + "px",
                    novel_font_size.to(str) + "px"
                ),
                color=el["color"],
                white_space="pre-wrap",
                line_height="1.8",
                text_align=rx.cond(el["text_align"], el["text_align"], "left")
            ),
            position="relative", width="100%", padding="20px",
            background_color=el["bg_color"], z_index=el["z_index"],
            pointer_events="none"
        )),
        ("markdown", rx.box(
            rx.markdown(
                el["content"],
                font_size=rx.cond(
                    el["font_size"],
                    (el["font_size"].to(float) * novel_font_size / 24.0).to(str) + "px",
                    novel_font_size.to(str) + "px"
                ),
                color=el["color"],
                background_color=el["bg_color"],
            ),
            position="relative", width="100%", padding="40px",
            background_color=el["bg_color"], z_index=el["z_index"],
        )),

        rx.fragment()
    )

def book_card(book: Dict[str, Any]) -> rx.Component:
    return rx.card(
        rx.inset(rx.image(src=book["cover_src"], width="100%", height="250px", object_fit="cover"), side="top", pb="current"),
        rx.vstack(rx.heading(book["title"], size="4", weight="bold"), rx.text(f"Author: {book['author']}", size="2", color_scheme="gray"), rx.button("Read", on_click=lambda: State.select_book(book["id"]), width="100%", color_scheme="blue", variant="surface"), align_items="start", spacing="2"),
        width="200px",
    )

def bgm_controls() -> rx.Component:
    return rx.hstack(
        rx.audio(src="/bgm.mp3", playing=State.is_playing_bgm, volume=State.bgm_volume, loop=True, controls=False, display="none"),
        rx.popover.root(
            rx.popover.trigger(rx.button(rx.cond(State.is_playing_bgm, rx.icon("volume-2", color="green"), rx.icon("volume-x", color="red")), variant="ghost", size="2")),
            rx.popover.content(rx.vstack(rx.hstack(rx.text("Volume", size="1"), rx.spacer(), rx.text(State.bgm_volume_percent, size="1"), width="100%"), rx.slider(default_value=[50], on_value_commit=State.set_bgm_volume, width="150px"), rx.button(rx.cond(State.is_playing_bgm, "Stop", "Start"), on_click=State.toggle_bgm, size="1", width="100%", color_scheme=rx.cond(State.is_playing_bgm, "red", "green")), spacing="3", padding="2")),
        ),
        align_items="center", spacing="2",
    )

def navigation_controls(show_jump: bool = True) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.button("« Prev Vol", on_click=State.prev_volume, disabled=~State.has_prev_volume, variant="soft"),
            rx.button("Prev Page", on_click=State.prev_page, disabled=State.current_page_idx == 0),
            rx.text(State.page_display_text),
            rx.button("Next Page", on_click=State.next_page, disabled=State.current_page_idx >= State.pages_list.length() - 1),
            rx.button("Next Vol »", on_click=State.next_volume, disabled=~State.has_next_volume, variant="soft"),
            justify="center", width="100%", padding_y="2", spacing="3"
        ),
        rx.cond(
            show_jump,
            rx.hstack(
                rx.input(placeholder="Jump to page...", value=State.jump_page_input, on_change=State.set_jump_page_input, width="120px", size="2"),
                rx.button("Go", on_click=State.jump_to_page, size="2"),
                justify="center", width="100%", padding_bottom="2"
            )
        ),
        width="100%"
    )

def login_page() -> rx.Component:
    return rx.center(
        rx.vstack(
            # Premium Glow Background Card (Glassmorphism)
            rx.vstack(
                # Title & Logo
                rx.vstack(
                    rx.heading(
                        "Venus Reader",
                        size="9",
                        weight="bold",
                        background_image="linear-gradient(135deg, #FF007F, #7F00FF)",
                        background_clip="text",
                        color="transparent",
                        margin_bottom="1",
                    ),
                    rx.text("Private Matchmaking Connection Panel", size="2", color="#aaa", text_transform="uppercase", letter_spacing="2px"),
                    align_items="center",
                    spacing="1",
                    margin_bottom="6",
                ),
                
                # Room ID Input
                rx.vstack(
                    rx.text("Room ID", size="2", weight="medium", color="#ccc"),
                    rx.input(
                        placeholder="e.g. 5S8A2",
                        value=State.room_id_input,
                        on_change=State.set_room_id_input,
                        size="3",
                        width="100%",
                        style={
                            "background": "rgba(255, 255, 255, 0.05)",
                            "border": "1px solid rgba(255, 255, 255, 0.1)",
                            "color": "#fff",
                        }
                    ),
                    align_items="start",
                    width="100%",
                    spacing="1",
                ),
                
                # Password Input
                rx.vstack(
                    rx.text("Password", size="2", weight="medium", color="#ccc"),
                    rx.input(
                        placeholder="••••••••",
                        type="password",
                        value=State.password_input,
                        on_change=State.set_password_input,
                        size="3",
                        width="100%",
                        style={
                            "background": "rgba(255, 255, 255, 0.05)",
                            "border": "1px solid rgba(255, 255, 255, 0.1)",
                            "color": "#fff",
                        }
                    ),
                    align_items="start",
                    width="100%",
                    spacing="1",
                    margin_top="3",
                ),
                
                # Status Alert if any
                rx.cond(
                    State.connection_status != "",
                    rx.box(
                        rx.hstack(
                            rx.icon("info", size=18, color="#ff4a9a"),
                            rx.text(State.connection_status, size="2", color="#ff4a9a", weight="medium"),
                            spacing="2",
                            align_items="center",
                        ),
                        width="100%",
                        padding="3",
                        background_color="rgba(255, 74, 154, 0.1)",
                        border="1px solid rgba(255, 74, 154, 0.2)",
                        border_radius="md",
                        margin_top="4",
                    )
                ),
                
                # Action Buttons
                rx.button(
                    rx.cond(State.is_connecting, "Connecting...", "Connect via MQTT"),
                    on_click=State.connect_to_mqtt_server,
                    size="3",
                    width="100%",
                    color_scheme="pink",
                    variant="solid",
                    margin_top="6",
                    loading=State.is_connecting,
                    style={
                        "background": "linear-gradient(135deg, #FF007F, #7F00FF)",
                        "box-shadow": "0 4px 15px rgba(255, 0, 127, 0.4)",
                        "_hover": {
                            "transform": "translateY(-1px)",
                            "box-shadow": "0 6px 20px rgba(255, 0, 127, 0.6)",
                        },
                        "transition": "all 0.2s ease-in-out",
                    }
                ),
                
                rx.hstack(
                    rx.divider(style={"border-color": "rgba(255,255,255,0.1)"}),
                    rx.text("OR", size="1", color="#666", padding_x="2"),
                    rx.divider(style={"border-color": "rgba(255,255,255,0.1)"}),
                    width="100%",
                    align_items="center",
                    margin_y="4",
                ),
                
                rx.button(
                    "Local Mode (Offline)",
                    on_click=State.enter_local_mode,
                    size="3",
                    width="100%",
                    color_scheme="gray",
                    variant="outline",
                    style={
                        "border": "1px solid rgba(255, 255, 255, 0.2)",
                        "color": "#fff",
                        "_hover": {
                            "background": "rgba(255,255,255,0.05)",
                        }
                    }
                ),
                
                width="100%",
                padding="8",
                background="rgba(20, 20, 20, 0.6)",
                backdrop_filter="blur(16px)",
                border="1px solid rgba(255, 255, 255, 0.08)",
                border_radius="24px",
                box_shadow="0 20px 40px rgba(0,0,0,0.5)",
            ),
            width="100%",
            max_width="450px",
            padding="4",
        ),
        width="100vw",
        height="100vh",
        background="radial-gradient(circle at top right, #1a0b2e, #0a0515)",
        overflow="hidden",
    )

def index() -> rx.Component:
    return rx.cond(
        State.is_logged_in,
        rx.container(
            rx.vstack(
                rx.hstack(
                    rx.heading("Venus Reader", size="9"),
                    rx.spacer(),
                    rx.button("Logout", on_click=State.logout, variant="soft", color_scheme="red"),
                    bgm_controls(),
                    width="100%",
                    padding_y="6"
                ),
                rx.debounce_input(
                    rx.input(
                        placeholder="Search title, author or category...",
                        width="100%",
                        size="3",
                        margin_bottom="4",
                        on_change=State.set_search_query,
                    ),
                    debounce_timeout=300,
                ),
                rx.foreach(
                    State.filtered_categories,
                    lambda main_cat: rx.vstack(
                        rx.hstack(
                            rx.heading(main_cat[0], size="6", border_left="4px solid var(--accent-9)", padding_left="3"),
                            rx.spacer(),
                            rx.button(rx.cond(State.expanded_categories.contains(main_cat[0]), rx.icon("chevron-up"), rx.icon("chevron-down")), on_click=lambda: State.toggle_category(main_cat[0]), variant="ghost", size="1"),
                            on_click=lambda: State.toggle_category(main_cat[0]),
                            width="100%", cursor="pointer", padding_y="2"
                        ),
                        rx.cond(
                            State.expanded_categories.contains(main_cat[0]),
                            rx.vstack(
                                rx.foreach(
                                    main_cat[1],
                                    lambda sub_cat: rx.vstack(
                                        # Sub-category Header (if name is not empty)
                                        rx.cond(
                                            sub_cat[0] != "",
                                            rx.hstack(
                                                rx.heading(sub_cat[0], size="4", color_scheme="gray", margin_left="4"),
                                                rx.spacer(),
                                                rx.button(
                                                    rx.cond(State.expanded_subcategories.contains(main_cat[0] + "/" + sub_cat[0]), rx.icon("minus"), rx.icon("plus")),
                                                    variant="ghost", size="1"
                                                ),
                                                on_click=lambda: State.toggle_subcategory(main_cat[0] + "/" + sub_cat[0]),
                                                width="100%", cursor="pointer", padding_y="1", margin_top="2"
                                            )
                                        ),
                                        # Books (show if no subcategory name OR if expanded)
                                        rx.cond(
                                            (sub_cat[0] == "") | State.expanded_subcategories.contains(main_cat[0] + "/" + sub_cat[0]),
                                            rx.flex(rx.foreach(sub_cat[1], book_card), wrap="wrap", spacing="5", justify="start", width="100%", padding_y="4", padding_left=rx.cond(sub_cat[0] != "", "8", "0"))
                                        ),
                                        align_items="start", width="100%"
                                    )
                                ),
                                width="100%"
                            )
                        ),
                        align_items="start", width="100%"
                    )
                ),
                rx.cond(State.filtered_categories.length() == 0, rx.center(rx.text("No results found.", size="4", color_scheme="gray"), width="100%", padding="20")),
                spacing="5", padding="5", width="100%",
            ),
            on_mount=State.load_books
        ),
        login_page()
    )

def volume_selector() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.button("← Back to Library", on_click=State.go_back_to_library, variant="soft"),
            rx.heading("選擇集數", size="6"),
            rx.spacer(),
            align_items="center", width="100%", padding_y="4", border_bottom="1px solid #333"
        ),
        rx.vstack(
            rx.heading(State.current_book_info["title"], size="8", weight="bold"),
            rx.text(f"共收錄 {State.current_book_volumes_count} 部經典著作", size="3", color_scheme="gray"),
            align_items="center", width="100%", padding_y="6"
        ),
        rx.debounce_input(
            rx.input(
                placeholder="搜尋集數/書名（例如：七劍、萍蹤）...",
                width="100%",
                size="3",
                margin_bottom="6",
                on_change=State.set_volume_search_query,
            ),
            debounce_timeout=300,
        ),
        rx.grid(
            rx.foreach(
                State.filtered_volumes,
                lambda vol: rx.card(
                    rx.vstack(
                        rx.heading(vol["title"], size="3", weight="bold"),
                        rx.text(f"頁碼：第 {vol['start_page']} 頁 - 第 {vol['end_page']} 頁", size="1", color_scheme="gray"),
                        rx.spacer(),
                        rx.button("開始閱讀", on_click=lambda: State.select_volume(vol["index"]), width="100%", color_scheme="blue", variant="solid"),
                        align_items="start", spacing="2", height="100%"
                    ),
                    padding="4",
                    width="100%",
                )
            ),
            columns=rx.breakpoints(initial="1", sm="2", md="3", lg="4"),
            spacing="4",
            width="100%"
        ),
        rx.cond(State.filtered_volumes.length() == 0, rx.center(rx.text("無符合搜尋條件的集數。", size="4", color_scheme="gray"), width="100%", padding="20")),
        width="100%"
    )

def reader() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.box(id="reader-top", width="100%", height="0px"),
            rx.cond(
                State.selected_book_id != "",
                rx.cond(
                    State.has_volumes & (State.selected_volume_index == -1),
                    volume_selector(),
                    rx.vstack(
                        rx.hstack(
                            rx.button("← Back", on_click=State.go_back_to_library, variant="soft"),
                            rx.heading(
                                rx.cond(
                                    State.active_volume_info["active"],
                                    State.active_volume_info["title"],
                                    State.current_book_info["title"]
                                ),
                                size="6"
                            ),
                            rx.hstack(
                                rx.cond(State.selected_volume_index != -1, rx.button("集數目錄", on_click=State.exit_volume, variant="outline", size="2")),
                                rx.cond(State.current_book_info["type"] == "novel", rx.popover.root(rx.popover.trigger(rx.button(rx.icon("type"), variant="outline", size="2")), rx.popover.content(rx.vstack(rx.text("Font Size: " + State.novel_font_size.to(str) + "px", size="1"), rx.slider(min=12, max=40, value=[State.novel_font_size], on_change=State.set_novel_font_size, width="120px"), padding="2")))),
                                rx.button(rx.cond(State.is_dual_mode, "Single", "Dual"), on_click=State.toggle_reading_mode, size="2", variant="outline"),
                                bgm_controls(), spacing="3",
                            ),
                            justify="between", align_items="center", width="100%", padding_y="4", border_bottom="1px solid #333",
                        ),
                        navigation_controls(show_jump=True),
                        rx.box(id="reading-start", width="100%", height="0px"),
                        rx.box(
                            rx.hstack(
                                rx.box(rx.foreach(State.page_elements_left, lambda el: render_element(el, State.current_book_info, State.novel_font_size)), width=rx.cond(State.is_dual_mode, "50%", "100%"), position="relative", min_height="70vh", overflow_y="auto"),
                                rx.cond(State.is_dual_mode, rx.box(rx.foreach(State.page_elements_right, lambda el: render_element(el, State.current_book_info, State.novel_font_size)), width="50%", position="relative", border_left="1px solid #333", min_height="70vh", overflow_y="auto")),
                                width="100%", align_items="start", spacing="0"
                            ),
                            rx.hstack(
                                rx.vstack(
                                    rx.box(on_click=State.prev_page, width="100%", height="33%", cursor="pointer", pointer_events="auto"),
                                    rx.box(on_click=State.next_page, width="100%", height="67%", cursor="pointer", pointer_events="auto"),
                                    width="33%", height="100%", spacing="0"
                                ),
                                rx.box(width="34%", height="100%", pointer_events="none"),
                                rx.box(on_click=State.next_page, width="33%", height="100%", cursor="pointer", pointer_events="auto"),
                                width="100%", height="100%", position="absolute", top="0", left="0", z_index="10",
                                pointer_events="none",
                            ),
                            width="100%", position="relative", background_color="#1a1a1a", min_height="70vh",
                        ),
                        navigation_controls(show_jump=True),
                        rx.box(rx.heading("Suggestions", size="4"), rx.text_area(value=State.suggestion_text, on_change=State.set_suggestion_text, placeholder="Enter suggestion...", width="100%", margin_y="2"), rx.button("Submit", on_click=State.submit_suggestion, color_scheme="blue"), width="100%", padding="4", margin_top="8", border="1px solid #333", border_radius="md"),
                        width="100%", align_items="center"
                    )
                ),
                rx.vstack(rx.text("No book selected."), rx.button("Go to Library", on_click=State.go_back_to_library), align_items="center", padding="20")
            ),
            spacing="5", padding="5", width="100%", max_width="1200px", margin="0 auto"
        ),
    )

app = rx.App()

# Custom API route to serve assets from ZIP archives
async def get_zip_asset(request: Request):
    book_id = request.path_params.get("book_id")
    asset_name = request.path_params.get("asset_name")
    
    global _library_cache
    loop = asyncio.get_running_loop()
    
    if not _library_cache:
        print("API: Library cache empty, triggering reload...")
        # Use executor to avoid blocking the main event loop
        books, _ = await loop.run_in_executor(_io_executor, _blocking_load_books)
        with _library_cache_lock:
            if not _library_cache:  # Double check
                _library_cache = books

    book = next((b for b in _library_cache if b["id"] == book_id), None)
    if not book:
        print(f"API: Book {book_id} not found in cache")
        return Response(status_code=404)
    if not book.get("is_zip"):
        print(f"API: Book {book_id} is not a ZIP")
        return Response(status_code=404)
    if not asset_name:
        return Response(status_code=404)
    
    try:
        def _read_zip_data():
            with zipfile.ZipFile(book["zip_path"], 'r') as z:
                internal_path = os.path.normpath(os.path.join(book["zip_internal_prefix"], "assets", asset_name)).lstrip('./')
                return z.read(internal_path)
        
        content = await loop.run_in_executor(_io_executor, _read_zip_data)
        ext = Path(asset_name).suffix.lower()
        media_types = {'.webp': 'image/webp', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif'}
        return Response(content=content, media_type=media_types.get(ext, 'application/octet-stream'))
    except Exception as e:
        print(f"API Error serving zip asset {asset_name} from {book_id}: {e}")
        return Response(status_code=404)

# Register the custom route on the underlying Starlette app
app._api.add_route("/api/zip_asset/{book_id}/{asset_name:path}", get_zip_asset)

app.add_page(index, route="/")
app.add_page(reader, route="/reader")
