import reflex as rx
import json
import re
from pathlib import Path
from typing import Any, List, Dict, Optional

# Paths
BANK_DIR = Path("/home/toby/documents/projects/venus-reflex/bank")
SUGGESTIONS_FILE = Path("/home/toby/documents/projects/venus-reflex/suggestions.json")

def natural_sort_key(s: str):
    """Helper to sort strings containing numbers in human order (1, 2, 10 instead of 1, 10, 2)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

class State(rx.State):
    all_books: List[Dict[str, Any]] = []
    search_query: str = ""
    
    selected_book_id: str = ""
    current_book_info: Dict[str, Any] = {}
    pages_list: List[str] = []
    current_page_idx: int = 0
    
    # Reader State
    page_elements_left: List[Dict[str, Any]] = []
    page_elements_right: List[Dict[str, Any]] = []
    is_dual_mode: bool = False
    
    # Novel specific state
    novel_font_size: int = 24
    
    suggestion_text: str = ""
    
    # BGM State
    is_playing_bgm: bool = False
    bgm_volume: float = 0.5

    def load_books(self):
        self.all_books = []
        if BANK_DIR.exists():
            for book_dir in BANK_DIR.iterdir():
                if book_dir.is_dir():
                    manifest_path = book_dir / "manifest.json"
                    if manifest_path.exists():
                        with open(manifest_path, 'r', encoding='utf-8') as f:
                            manifest = json.load(f)
                            # Find actual cover image (from the first page JSON)
                            pages_path = book_dir / "pages"
                            cover_file = ""
                            if pages_path.exists():
                                first_page = pages_path / "0001.json"
                                if first_page.exists():
                                    try:
                                        with open(first_page, 'r') as pf:
                                            page_data = json.load(pf)
                                            # Look for the first image element
                                            for el in page_data.get("elements", []):
                                                if el.get("type") == "image":
                                                    cover_file = Path(el["src"]).name
                                                    break
                                    except: pass

                            # Fallback if no pages exist or parsing fails
                            if not cover_file:
                                assets_path = book_dir / "assets"
                                if assets_path.exists():
                                    all_imgs = sorted([
                                        img_f.name for img_f in assets_path.iterdir() 
                                        if img_f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp')
                                    ], key=natural_sort_key)
                                    if all_imgs: cover_file = all_imgs[0]

                            manifest["cover_src"] = f"/bank/{manifest['id']}/assets/{cover_file}" if cover_file else ""
                            self.all_books.append(manifest)
        
        # Sort all books naturally by title
        self.all_books = sorted(self.all_books, key=lambda x: natural_sort_key(x.get("title", "")))

    @rx.var
    def filtered_categories(self) -> Dict[str, List[Dict[str, Any]]]:
        """Dynamically filter books based on search_query and group by category with natural sorting."""
        result = {}
        query = self.search_query.lower()
        
        for book in self.all_books:
            title = book.get("title", "").lower()
            author = book.get("author", "").lower()
            category = book.get("category", "未分類").lower()
            
            if query in title or query in author or query in category:
                cat = book.get("category", "未分類")
                if cat not in result:
                    result[cat] = []
                result[cat].append(book)
        
        # Sort categories and books inside categories naturally
        sorted_result = {
            k: sorted(v, key=lambda x: natural_sort_key(x.get("title", ""))) 
            for k, v in sorted(result.items(), key=lambda item: natural_sort_key(item[0]))
        }
        return sorted_result

    def set_search_query(self, query: str):
        self.search_query = query

    def select_book(self, book_id: str):
        book = next((b for b in self.all_books if b["id"] == book_id), None)
        if not book:
            return
            
        self.selected_book_id = book_id
        self.current_book_info = book
        
        book_path = BANK_DIR / self.selected_book_id
        pages_dir = book_path / "pages"
        
        if pages_dir.exists():
            self.pages_list = sorted([f.name for f in pages_dir.glob("*.json")])
            self.current_page_idx = 0
            self.load_current_page()
            
        return rx.redirect("/reader")

    def _load_page_json(self, idx: int) -> List[Dict[str, Any]]:
        if 0 <= idx < len(self.pages_list):
            page_file = self.pages_list[idx]
            page_path = BANK_DIR / self.selected_book_id / "pages" / page_file
            if page_path.exists():
                with open(page_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("elements", [])
        return []

    def load_current_page(self):
        if not self.selected_book_id or not self.pages_list:
            self.page_elements_left = []
            self.page_elements_right = []
            return
            
        self.page_elements_left = self._load_page_json(self.current_page_idx)
        if self.is_dual_mode:
            self.page_elements_right = self._load_page_json(self.current_page_idx + 1)
        else:
            self.page_elements_right = []
        self.suggestion_text = ""
        
        # Scroll to top
        return rx.scroll_to("reader-top")

    def toggle_reading_mode(self):
        self.is_dual_mode = not self.is_dual_mode
        self.load_current_page()

    def set_novel_font_size(self, size: list[int]):
        self.novel_font_size = size[0]

    def next_page(self):
        step = 2 if self.is_dual_mode else 1
        if self.current_page_idx + step < len(self.pages_list):
            self.current_page_idx += step
            return self.load_current_page()
        elif self.is_dual_mode and self.current_page_idx + 1 < len(self.pages_list):
             self.current_page_idx += 1
             return self.load_current_page()

    def prev_page(self):
        step = 2 if self.is_dual_mode else 1
        if self.current_page_idx - step >= 0:
            self.current_page_idx -= step
        else:
            self.current_page_idx = 0
        return self.load_current_page()

    def next_volume(self):
        cat = self.current_book_info.get("category", "未分類")
        cat_books = [b for b in self.all_books if b.get("category", "未分類") == cat]
        # cat_books is already naturally sorted because all_books was sorted
        current_idx = next((i for i, b in enumerate(cat_books) if b["id"] == self.selected_book_id), -1)
        if current_idx != -1 and current_idx + 1 < len(cat_books):
            return self.select_book(cat_books[current_idx + 1]["id"])

    def prev_volume(self):
        cat = self.current_book_info.get("category", "未分類")
        cat_books = [b for b in self.all_books if b.get("category", "未分類") == cat]
        current_idx = next((i for i, b in enumerate(cat_books) if b["id"] == self.selected_book_id), -1)
        if current_idx > 0:
            return self.select_book(cat_books[current_idx - 1]["id"])

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
            except: pass
        suggestions.append(suggestion)
        with open(SUGGESTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(suggestions, f, ensure_ascii=False, indent=4)
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
        if self.is_dual_mode:
            end_idx = min(self.current_page_idx + 2, len(self.pages_list))
            return f"Pages {self.current_page_idx + 1}-{end_idx} / {len(self.pages_list)}"
        return f"Page {self.current_page_idx + 1} / {len(self.pages_list)}"

    @rx.var
    def has_prev_volume(self) -> bool:
        cat = self.current_book_info.get("category", "未分類")
        cat_books = [b for b in self.all_books if b.get("category", "未分類") == cat]
        current_idx = next((i for i, b in enumerate(cat_books) if b["id"] == self.selected_book_id), -1)
        return current_idx > 0

    @rx.var
    def has_next_volume(self) -> bool:
        cat = self.current_book_info.get("category", "未分類")
        cat_books = [b for b in self.all_books if b.get("category", "未分類") == cat]
        current_idx = next((i for i, b in enumerate(cat_books) if b["id"] == self.selected_book_id), -1)
        return current_idx != -1 and current_idx + 1 < len(cat_books)

def render_element(el: Any, book_id: Any, novel_font_size: Any) -> rx.Component:
    src_path = "/bank/" + book_id + "/" + el["src"].to(str)
    return rx.match(
        el["type"],
        ("image", rx.image(src=src_path, width="100%", height="auto", object_fit="contain", user_select="none", pointer_events="none")),
        ("text", rx.box(
            rx.text(
                el["content"], 
                font_size=novel_font_size.to(str) + "px", 
                color=el["color"],
                white_space="pre-wrap",
                line_height="1.8",
                text_align="left",
            ),
            position="relative",
            width="100%",
            padding="20px",
            background_color=el["bg_color"],
            z_index=el["z_index"],
            pointer_events="none"
        )),
        rx.fragment()
    )

def book_card(book: Dict[str, Any]) -> rx.Component:
    return rx.card(
        rx.inset(rx.image(src=book["cover_src"], width="100%", height="250px", object_fit="cover"), side="top", pb="current"),
        rx.vstack(
            rx.heading(book["title"], size="4", weight="bold"),
            rx.text(f"Author: {book['author']}", size="2", color_scheme="gray"),
            rx.button("Read", on_click=lambda: State.select_book(book["id"]), width="100%", color_scheme="blue", variant="surface"),
            align_items="start", spacing="2"
        ),
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

def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(rx.heading("Venus Reader", size="9"), rx.spacer(), bgm_controls(), width="100%", padding_y="6"),
            rx.input(placeholder="Search by title, author or category...", on_change=State.set_search_query, width="100%", size="3", margin_bottom="4"),
            rx.foreach(
                State.filtered_categories,
                lambda cat: rx.vstack(
                    rx.heading(cat[0], size="6", margin_top="6", border_left="4px solid var(--accent-9)", padding_left="3"),
                    rx.flex(rx.foreach(cat[1], book_card), wrap="wrap", spacing="5", justify="start", width="100%", padding_y="4"
                    ),
                    align_items="start", width="100%"
                )
            ),
            rx.cond(State.filtered_categories.length() == 0, rx.center(rx.text("No results found.", size="4", color_scheme="gray"), width="100%", padding="20")),
            spacing="5", padding="5", width="100%",
        ),
        on_mount=State.load_books
    )

def reader() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.box(id="reader-top", width="100%", height="0px"),
            rx.hstack(
                rx.button("← Back", on_click=State.go_back_to_library, variant="soft"),
                rx.heading(State.current_book_info["title"], size="6"),
                rx.hstack(
                    rx.cond(
                        State.current_book_info["type"] == "novel",
                        rx.popover.root(
                            rx.popover.trigger(rx.button(rx.icon("type"), variant="outline", size="2")),
                            rx.popover.content(rx.vstack(rx.text(f"Font Size: {State.novel_font_size}px", size="1"), rx.slider(min=12, max=64, default_value=[24], on_value_commit=State.set_novel_font_size, width="120px"), padding="2"))
                        )
                    ),
                    rx.button(rx.cond(State.is_dual_mode, "Single", "Dual"), on_click=State.toggle_reading_mode, size="2", variant="outline"),
                    bgm_controls(),
                    spacing="3",
                ),
                justify="between", align_items="center", width="100%", padding_y="4", border_bottom="1px solid #333"
            ),
            rx.cond(
                State.selected_book_id != "",
                rx.vstack(
                    rx.hstack(
                        rx.button("« Prev Vol", on_click=State.prev_volume, disabled=~State.has_prev_volume, variant="soft"),
                        rx.button("Prev Page", on_click=State.prev_page, disabled=State.current_page_idx == 0),
                        rx.text(State.page_display_text),
                        rx.button("Next Page", on_click=State.next_page, disabled=State.current_page_idx >= State.pages_list.length() - 1),
                        rx.button("Next Vol »", on_click=State.next_volume, disabled=~State.has_next_volume, variant="soft"),
                        justify="center", width="100%", padding="4", spacing="3"
                    ),
                    rx.box(
                        rx.hstack(
                            rx.box(rx.foreach(State.page_elements_left, lambda el: render_element(el, State.selected_book_id, State.novel_font_size)), width=rx.cond(State.is_dual_mode, "50%", "100%"), position="relative", min_height="70vh", overflow_y="auto"),
                            rx.cond(State.is_dual_mode, rx.box(rx.foreach(State.page_elements_right, lambda el: render_element(el, State.selected_book_id, State.novel_font_size)), width="50%", position="relative", border_left="1px solid #333", min_height="70vh", overflow_y="auto")),
                            width="100%", align_items="start", spacing="0"
                        ),
                        rx.hstack(
                            rx.box(on_click=State.prev_page, width="33%", height="100%", cursor="pointer"),
                            rx.box(width="34%", height="100%"),
                            rx.box(on_click=State.next_page, width="33%", height="100%", cursor="pointer"),
                            width="100%", height="100%", position="absolute", top="0", left="0", z_index="10",
                        ),
                        width="100%", position="relative", background_color="#1a1a1a", min_height="70vh",
                    ),
                    rx.hstack(
                        rx.button("« Prev Vol", on_click=State.prev_volume, disabled=~State.has_prev_volume, variant="soft"),
                        rx.button("Prev Page", on_click=State.prev_page, disabled=State.current_page_idx == 0),
                        rx.text(State.page_display_text),
                        rx.button("Next Page", on_click=State.next_page, disabled=State.current_page_idx >= State.pages_list.length() - 1),
                        rx.button("Next Vol »", on_click=State.next_volume, disabled=~State.has_next_volume, variant="soft"),
                        justify="center", width="100%", padding="4", spacing="3", margin_top="4"
                    ),
                    rx.box(
                        rx.heading("Suggestions", size="4"),
                        rx.text_area(value=State.suggestion_text, on_change=State.set_suggestion_text, placeholder="Enter suggestion...", width="100%", margin_y="2"),
                        rx.button("Submit", on_click=State.submit_suggestion, color_scheme="blue"),
                        width="100%", padding="4", margin_top="8", border="1px solid #333", border_radius="md"
                    ),
                    width="100%", align_items="center"
                ),
                rx.vstack(rx.text("No book selected."), rx.button("Go to Library", on_click=State.go_back_to_library), align_items="center", padding="20")
            ),
            spacing="5", padding="5", width="100%", max_width="1200px", margin="0 auto"
        ),
    )

app = rx.App(theme=rx.theme(appearance="dark", accent_color="blue"))
app.add_page(index, route="/")
app.add_page(reader, route="/reader")
