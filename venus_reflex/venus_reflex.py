import reflex as rx
import json
from pathlib import Path
from typing import Any, List, Dict, Optional

# Paths
BANK_DIR = Path("/home/toby/documents/projects/venus-reflex/bank")
SUGGESTIONS_FILE = Path("/home/toby/documents/projects/venus-reflex/suggestions.json")

class State(rx.State):
    books: List[Dict[str, Any]] = []
    selected_book_id: str = ""
    current_book_info: Dict[str, Any] = {}
    pages_list: List[str] = []
    current_page_idx: int = 0
    current_page_data: Dict[str, Any] = {}
    page_elements: List[Dict[str, Any]] = []
    suggestion_text: str = ""

    def load_books(self):
        self.books = []
        if BANK_DIR.exists():
            for book_dir in BANK_DIR.iterdir():
                if book_dir.is_dir():
                    manifest_path = book_dir / "manifest.json"
                    if manifest_path.exists():
                        with open(manifest_path, 'r', encoding='utf-8') as f:
                            manifest = json.load(f)
                            self.books.append(manifest)
        self.books = sorted(self.books, key=lambda x: x.get("title", ""))

    def select_book(self, book_title: str):
        book = next((b for b in self.books if b["title"] == book_title), None)
        if not book:
            return
            
        self.selected_book_id = book["id"]
        self.current_book_info = book
        
        book_path = BANK_DIR / self.selected_book_id
        pages_dir = book_path / "pages"
        
        if pages_dir.exists():
            self.pages_list = sorted([f.name for f in pages_dir.glob("*.json")])
            self.current_page_idx = 0
            self.load_current_page()

    def load_current_page(self):
        if not self.selected_book_id or not self.pages_list:
            self.current_page_data = {}
            self.page_elements = []
            return
            
        page_file = self.pages_list[self.current_page_idx]
        page_path = BANK_DIR / self.selected_book_id / "pages" / page_file
        
        if page_path.exists():
            with open(page_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.current_page_data = data
                self.page_elements = data.get("elements", [])
        
        self.suggestion_text = ""

    def next_page(self):
        if self.pages_list and self.current_page_idx < len(self.pages_list) - 1:
            self.current_page_idx += 1
            self.load_current_page()

    def prev_page(self):
        if self.pages_list and self.current_page_idx > 0:
            self.current_page_idx -= 1
            self.load_current_page()

    def set_suggestion_text(self, text: str):
        self.suggestion_text = text

    def submit_suggestion(self):
        if not self.selected_book_id or not self.pages_list:
            return
            
        suggestion = {
            "book_id": self.selected_book_id,
            "book_title": self.current_book_info.get("title"),
            "page_index": self.current_page_idx,
            "page_file": self.pages_list[self.current_page_idx],
            "suggestion": self.suggestion_text
        }
        
        suggestions = []
        if SUGGESTIONS_FILE.exists():
            try:
                with open(SUGGESTIONS_FILE, 'r', encoding='utf-8') as f:
                    suggestions = json.load(f)
            except:
                pass
                
        suggestions.append(suggestion)
        
        with open(SUGGESTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(suggestions, f, ensure_ascii=False, indent=4)
            
        self.suggestion_text = ""
        return rx.toast("Suggestion saved!")

    @rx.var
    def book_titles(self) -> List[str]:
        return [b["title"] for b in self.books]

def render_element(el: Any, book_id: Any) -> rx.Component:
    src_path = "/bank/" + book_id + "/" + el["src"].to(str)
    
    return rx.match(
        el["type"],
        ("image", rx.image(
            src=src_path,
            width="100%",
            height="auto",
            object_fit="contain",
            user_select="none"
        )),
        ("text", rx.box(
            rx.text(el["content"], font_size=el["font_size"].to(str) + "px", color=el["color"]),
            position="absolute",
            left=el["x"].to(str) + "px",
            top=el["y"].to(str) + "px",
            background_color=el["bg_color"],
            padding="2px",
            z_index=el["z_index"],
            pointer_events="none"
        )),
        rx.fragment()
    )

def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.heading("Venus Reader (VBF Mode)", size="8"),
            
            rx.hstack(
                rx.select(
                    State.book_titles,
                    placeholder="Select a book...",
                    on_change=State.select_book,
                    width="100%"
                ),
                rx.button("Refresh", on_click=State.load_books),
                width="100%"
            ),
            
            rx.cond(
                State.selected_book_id != "",
                rx.vstack(
                    rx.hstack(
                        rx.button("Previous", on_click=State.prev_page, disabled=State.current_page_idx == 0),
                        rx.text(f"Page {State.current_page_idx + 1} / {State.pages_list.length()}"),
                        rx.button("Next", on_click=State.next_page, disabled=State.current_page_idx == State.pages_list.length() - 1),
                        justify="center",
                        width="100%",
                        padding="4"
                    ),
                    
                    # Canvas Area with Transparent Navigation Overlay
                    rx.box(
                        # 1. The Content Layer
                        rx.box(
                            rx.foreach(
                                State.page_elements,
                                lambda el: render_element(el, State.selected_book_id)
                            ),
                            width="100%",
                            position="relative",
                        ),
                        
                        # 2. The Transparent Hit Zones Overlay
                        rx.hstack(
                            # Left Zone (Prev)
                            rx.box(
                                on_click=State.prev_page,
                                width="33%",
                                height="100%",
                                cursor="pointer",
                                # background_color="rgba(255,0,0,0.1)", # For debugging
                            ),
                            # Center Zone (Nothing for now)
                            rx.box(
                                width="34%",
                                height="100%",
                            ),
                            # Right Zone (Next)
                            rx.box(
                                on_click=State.next_page,
                                width="33%",
                                height="100%",
                                cursor="pointer",
                                # background_color="rgba(0,255,0,0.1)", # For debugging
                            ),
                            width="100%",
                            height="100%",
                            position="absolute",
                            top="0",
                            left="0",
                            z_index="10",
                        ),
                        
                        width="100%",
                        position="relative",
                        background_color="#1a1a1a",
                        min_height="50vh",
                    ),
                    
                    rx.box(
                        rx.heading("Suggestions", size="4"),
                        rx.text_area(
                            value=State.suggestion_text,
                            on_change=State.set_suggestion_text,
                            placeholder="Enter suggestion for this page...",
                            width="100%",
                            margin_y="2"
                        ),
                        rx.button("Submit", on_click=State.submit_suggestion, color_scheme="blue"),
                        width="100%",
                        padding="4",
                        margin_top="4",
                        border="1px solid #333",
                        border_radius="md"
                    ),
                    
                    width="100%",
                    align_items="center"
                ),
                rx.text("Welcome! Please select a book.")
            ),
            
            spacing="5",
            padding="5",
            width="100%",
            max_width="1000px",
            margin="0 auto"
        ),
        on_mount=State.load_books
    )

app = rx.App(
    theme=rx.theme(appearance="dark")
)
app.add_page(index)
