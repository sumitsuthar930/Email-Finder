"""
================================================================
  PUBLIC CONTACT EMAIL FINDER — GUI EDITION
  Serper.dev (Google Search) based OSINT email discovery tool
================================================================

Requires a .env file (same folder as this script) with:
    SERPER_API_KEY=your_key_here

Get a free API key at: https://serper.dev

Install dependencies:
    pip install requests python-dotenv pypdf

Run:
    python email_finder_gui.py
"""

import os
import re
import csv
import io
import random
import threading
import queue
from datetime import datetime

import requests
from dotenv import load_dotenv

try:
    from pypdf import PdfReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

import tkinter as tk
from tkinter import ttk, messagebox, filedialog


# ==========================================
# Theme constants
# ==========================================

BG_MAIN = "#0a0e0f"
BG_PANEL = "#0f1618"
BG_INPUT = "#101a1c"
FG_ACCENT = "#00ff9c"
FG_ACCENT_DIM = "#0aa06a"
FG_TEXT = "#c8f5e0"
FG_MUTED = "#5b8f7c"
FG_ERROR = "#ff5c5c"
FONT_MONO = ("Consolas", 10)
FONT_MONO_BOLD = ("Consolas", 11, "bold")
FONT_TITLE = ("Consolas", 16, "bold")


# ==========================================
# Email pattern
# ==========================================

EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+"
    r"@[A-Za-z0-9.-]+\."
    r"[A-Za-z]{2,}\b"
)


def extract_emails(text):
    if not text:
        return set()
    return set(EMAIL_REGEX.findall(text))


# ==========================================
# PDF deep-scan helper
# ==========================================

MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB safety cap


def is_pdf_result(item):
    link = item.get("link", "").lower()
    file_format = item.get("fileFormat", "").lower()
    return link.endswith(".pdf") or "pdf" in file_format


def download_and_extract_pdf_text(url, timeout=25):
    """Downloads a PDF and returns its full text, or raises on failure."""
    if not PDF_SUPPORT:
        raise RuntimeError("pypdf not installed (pip install pypdf)")

    response = requests.get(url, timeout=timeout, stream=True)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    if "pdf" not in content_type and not url.lower().endswith(".pdf"):
        raise ValueError(f"Not a PDF (content-type: {content_type})")

    buffer = io.BytesIO()
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > MAX_PDF_BYTES:
            raise ValueError("PDF too large (>20MB), skipped")
        buffer.write(chunk)

    buffer.seek(0)
    reader = PdfReader(buffer)

    text_parts = []
    for page in reader.pages:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            continue

    return "\n".join(text_parts)


# ==========================================
# Search engine wrapper (Serper.dev)
# ==========================================

class SerperSearchClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.url = "https://google.serper.dev/search"

    def search(self, query, page=1):
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "q": query,
            "page": page,
            "num": 10,
            "gl": "in",
        }
        try:
            response = requests.post(self.url, headers=headers, json=payload, timeout=20)
        except requests.RequestException as error:
            return None, f"Network error: {error}"

        if response.status_code != 200:
            try:
                error_data = response.json()
                message = error_data.get("message", str(error_data))
            except ValueError:
                message = response.text
            return None, f"HTTP {response.status_code}: {message}"

        return response.json(), None


# ==========================================
# Matrix-style rain animation (decorative banner)
# ==========================================

MATRIX_CHARS = "アイウエオカキクケコサシスセソ01ABCDEFGHIJKLMNOPQRSTUVWXYZ$#@%&"


class MatrixRain(tk.Canvas):
    """A thin animated 'digital rain' strip, purely decorative."""

    def __init__(self, parent, height=54, **kwargs):
        super().__init__(
            parent, height=height, bg=BG_MAIN, highlightthickness=0, **kwargs
        )
        self.col_width = 14
        self.drops = {}  # column x -> current y (in char rows)
        self._running = True
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        cols = max(1, event.width // self.col_width)
        # keep existing drop positions where possible, add new columns as needed
        for c in range(cols):
            x = c * self.col_width
            if x not in self.drops:
                self.drops[x] = random.randint(-15, 0)

    def start(self):
        self._running = True
        self._tick()

    def stop(self):
        self._running = False

    def _tick(self):
        if not self._running:
            return
        self.delete("all")
        h = self.winfo_height() or 54
        rows = max(1, h // 16)

        for x, row in list(self.drops.items()):
            # draw a short fading trail
            for trail in range(6):
                r = row - trail
                if 0 <= r < rows:
                    char = random.choice(MATRIX_CHARS)
                    if trail == 0:
                        color = FG_TEXT
                    elif trail < 3:
                        color = FG_ACCENT
                    else:
                        color = FG_ACCENT_DIM
                    self.create_text(
                        x + 7, r * 16 + 10, text=char,
                        fill=color, font=("Consolas", 10), anchor="c",
                    )
            new_row = row + 1
            if new_row * 16 > h + 80:
                new_row = random.randint(-20, -1)
            self.drops[x] = new_row

        self.after(65, self._tick)


# ==========================================
# Worker thread — runs the search off the UI thread
# ==========================================

class SearchWorker(threading.Thread):
    def __init__(self, client, query, max_pages, log_queue, result_queue, stop_event,
                 deep_scan_pdfs=False):
        super().__init__(daemon=True)
        self.client = client
        self.query = query
        self.max_pages = max_pages
        self.log_queue = log_queue
        self.result_queue = result_queue
        self.stop_event = stop_event
        self.deep_scan_pdfs = deep_scan_pdfs

    def log(self, msg):
        self.log_queue.put(msg)

    def run(self):
        all_emails = set()
        rows = []

        self.log(f"[+] Query: {self.query}")

        for page_num in range(1, self.max_pages + 1):
            if self.stop_event.is_set():
                self.log("[!] Search cancelled by user.")
                break

            self.log(f"[+] Fetching page {page_num}...")

            data, error = self.client.search(self.query, page=page_num)

            if error:
                self.log(f"[X] ERROR: {error}")
                break

            if not data:
                break

            items = data.get("organic", [])
            if not items:
                self.log("[i] No more results.")
                break

            self.log(f"[+] Results received: {len(items)}")

            for item in items:
                title = item.get("title", "")
                link = item.get("link", "")
                snippet = item.get("snippet", "")

                text = f"{title} {snippet}"
                found = extract_emails(text)

                if found:
                    for email in found:
                        rows.append({
                            "email": email,
                            "source_title": title,
                            "source_url": link,
                        })
                    all_emails.update(found)
                    self.log(f"    -> {title[:60]}")
                    self.log(f"       {link}")
                    self.log(f"       emails: {', '.join(sorted(found))}")

                if self.deep_scan_pdfs and is_pdf_result(item):
                    if self.stop_event.is_set():
                        break
                    self.log(f"    [PDF] Deep-scanning: {link}")
                    try:
                        full_text = download_and_extract_pdf_text(link)
                        pdf_emails = extract_emails(full_text)
                        new_emails = pdf_emails - all_emails
                        if pdf_emails:
                            for email in pdf_emails:
                                rows.append({
                                    "email": email,
                                    "source_title": f"[PDF] {title}",
                                    "source_url": link,
                                })
                            all_emails.update(pdf_emails)
                            self.log(
                                f"    [PDF] Found {len(pdf_emails)} email(s) "
                                f"({len(new_emails)} new): {', '.join(sorted(pdf_emails))}"
                            )
                        else:
                            self.log("    [PDF] No emails found in document text.")
                    except Exception as pdf_error:
                        self.log(f"    [PDF] Skipped — {pdf_error}")

        self.log(f"[+] Done. {len(all_emails)} unique email(s) found.")
        self.result_queue.put(rows)


# ==========================================
# Main Application
# ==========================================

class EmailFinderApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("EMAIL-FINDER // OSINT Console")
        self.geometry("980x680")
        self.minsize(860, 600)
        self.configure(bg=BG_MAIN)

        self.log_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.rows = []  # last search results: list of dicts

        self.client = None
        self._load_credentials()

        self._build_style()
        self._build_layout()

        self._pulse_state = 0
        self._spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._spinner_index = 0
        self._searching = False

        self._run_boot_sequence()
        self._pulse_status_dot()
        self._poll_queues()

    # ------------------------------------------
    # Boot-up animation
    # ------------------------------------------

    def _run_boot_sequence(self):
        boot_lines = [
            "[BOOT] Initializing OSINT console...",
            "[BOOT] Loading credentials from .env ...",
            "[BOOT] Establishing search client ...",
            "[BOOT] PDF deep-scan: " + ("available" if PDF_SUPPORT else "unavailable (pip install pypdf)"),
            "[BOOT] Ready." if self.client else "[BOOT] FAILED — check credentials.",
        ]
        self.log_text.configure(state="normal")
        self._typewriter_lines(boot_lines, 0, 0)

    def _typewriter_lines(self, lines, line_idx, char_idx):
        if line_idx >= len(lines):
            self.log_text.configure(state="disabled")
            return

        line = lines[line_idx]
        tag = "error" if "FAILED" in line else "accent"

        if char_idx == 0:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.insert("end", f"[{timestamp}] ", ())

        if char_idx < len(line):
            self.log_text.insert("end", line[char_idx], (tag,))
            self.log_text.see("end")
            self.after(8, self._typewriter_lines, lines, line_idx, char_idx + 1)
        else:
            self.log_text.insert("end", "\n")
            self.after(120, self._typewriter_lines, lines, line_idx + 1, 0)

    # ------------------------------------------
    # Pulsing status dot (breathing effect when idle,
    # spinner effect when searching)
    # ------------------------------------------

    def _pulse_status_dot(self):
        if self._searching:
            frame = self._spinner_frames[self._spinner_index % len(self._spinner_frames)]
            self._spinner_index += 1
            base = "STOPPING" if self.stop_event.is_set() else "SEARCHING"
            color = FG_ERROR if self.stop_event.is_set() else FG_ACCENT
            self.status_dot.configure(text=frame, fg=color)
            self.status_label.configure(
                text=base + "." * (self._spinner_index % 4), fg=color
            )
            self.after(90, self._pulse_status_dot)
        else:
            colors = [FG_ACCENT_DIM, "#0d6b48", "#0aa06a", "#0d6b48"]
            color = colors[self._pulse_state % len(colors)]
            self._pulse_state += 1
            self.status_dot.configure(text="●", fg=color)
            self.after(450, self._pulse_status_dot)

    # ------------------------------------------
    # Credentials
    # ------------------------------------------

    def _load_credentials(self):
        load_dotenv()
        api_key = os.getenv("SERPER_API_KEY")

        if not api_key:
            messagebox.showerror(
                "Missing credentials",
                "SERPER_API_KEY not found in .env file.\n\n"
                "Create a .env file next to this script containing:\n"
                "SERPER_API_KEY=your_key\n\n"
                "Get a free key at https://serper.dev",
            )
            self.after(100, self.destroy)
            return

        self.client = SerperSearchClient(api_key)

    # ------------------------------------------
    # Style
    # ------------------------------------------

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(
            "Treeview",
            background=BG_INPUT,
            foreground=FG_TEXT,
            fieldbackground=BG_INPUT,
            font=FONT_MONO,
            rowheight=24,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=BG_PANEL,
            foreground=FG_ACCENT,
            font=FONT_MONO_BOLD,
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", FG_ACCENT_DIM)],
            foreground=[("selected", "#00140c")],
        )

        style.configure(
            "Accent.TButton",
            background=FG_ACCENT,
            foreground="#00140c",
            font=FONT_MONO_BOLD,
            borderwidth=0,
            padding=8,
        )
        style.map("Accent.TButton", background=[("active", FG_ACCENT_DIM)])

        style.configure(
            "Dark.TButton",
            background=BG_PANEL,
            foreground=FG_TEXT,
            font=FONT_MONO,
            borderwidth=1,
            padding=6,
        )
        style.map("Dark.TButton", background=[("active", "#16221f")])

        style.configure("TProgressbar", background=FG_ACCENT, troughcolor=BG_PANEL)

    # ------------------------------------------
    # Layout
    # ------------------------------------------

    def _build_layout(self):
        # Header
        header = tk.Frame(self, bg=BG_MAIN)
        header.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(
            header,
            text=">_ EMAIL-FINDER",
            bg=BG_MAIN,
            fg=FG_ACCENT,
            font=FONT_TITLE,
        ).pack(side="left")

        tk.Label(
            header,
            text="  OSINT public-contact discovery console",
            bg=BG_MAIN,
            fg=FG_MUTED,
            font=FONT_MONO,
        ).pack(side="left", padx=(4, 0))

        self.status_dot = tk.Label(
            header, text="●", bg=BG_MAIN, fg=FG_ACCENT_DIM, font=("Consolas", 14)
        )
        self.status_dot.pack(side="right")
        self.status_label = tk.Label(
            header, text="READY", bg=BG_MAIN, fg=FG_MUTED, font=FONT_MONO
        )
        self.status_label.pack(side="right", padx=(0, 6))

        # Matrix rain banner strip
        self.matrix = MatrixRain(self)
        self.matrix.pack(fill="x", padx=16, pady=(2, 8))
        self.matrix.start()

        # Search bar
        search_frame = tk.Frame(self, bg=BG_PANEL, highlightbackground=FG_ACCENT_DIM,
                                 highlightthickness=1)
        search_frame.pack(fill="x", padx=16, pady=6)

        tk.Label(
            search_frame, text=" QUERY", bg=BG_PANEL, fg=FG_MUTED, font=FONT_MONO
        ).pack(side="left", padx=(8, 4), pady=8)

        self.query_var = tk.StringVar()
        query_entry = tk.Entry(
            search_frame,
            textvariable=self.query_var,
            bg=BG_INPUT,
            fg=FG_ACCENT,
            insertbackground=FG_ACCENT,
            relief="flat",
            font=FONT_MONO,
        )
        query_entry.pack(side="left", fill="x", expand=True, padx=6, pady=8, ipady=4)
        query_entry.bind("<Return>", lambda e: self.start_search())

        tk.Label(
            search_frame, text="PAGES", bg=BG_PANEL, fg=FG_MUTED, font=FONT_MONO
        ).pack(side="left", padx=(6, 2))

        self.pages_var = tk.IntVar(value=3)
        pages_spin = tk.Spinbox(
            search_frame,
            from_=1,
            to=10,
            width=3,
            textvariable=self.pages_var,
            bg=BG_INPUT,
            fg=FG_ACCENT,
            relief="flat",
            font=FONT_MONO,
            buttonbackground=BG_PANEL,
        )
        pages_spin.pack(side="left", padx=(0, 8), pady=8)

        self.deep_scan_var = tk.BooleanVar(value=False)
        deep_scan_check = tk.Checkbutton(
            search_frame,
            text="DEEP-SCAN PDFs",
            variable=self.deep_scan_var,
            bg=BG_PANEL,
            fg=FG_TEXT,
            selectcolor=BG_INPUT,
            activebackground=BG_PANEL,
            activeforeground=FG_ACCENT,
            font=FONT_MONO,
            highlightthickness=0,
            relief="flat",
        )
        deep_scan_check.pack(side="left", padx=(0, 8), pady=8)
        if not PDF_SUPPORT:
            deep_scan_check.configure(state="disabled")

        self.search_btn = ttk.Button(
            search_frame, text="RUN SEARCH", style="Accent.TButton",
            command=self.start_search,
        )
        self.search_btn.pack(side="left", padx=(0, 4), pady=8)

        self.stop_btn = ttk.Button(
            search_frame, text="STOP", style="Dark.TButton",
            command=self.stop_search, state="disabled",
        )
        self.stop_btn.pack(side="left", padx=(0, 8), pady=8)

        # Progress bar
        self.progress = ttk.Progressbar(self, mode="indeterminate", style="TProgressbar")
        self.progress.pack(fill="x", padx=16, pady=(0, 6))

        # Split pane: log console (left) + results table (right)
        body = tk.Frame(self, bg=BG_MAIN)
        body.pack(fill="both", expand=True, padx=16, pady=6)

        # Log console
        log_frame = tk.Frame(body, bg=BG_PANEL, highlightbackground=FG_ACCENT_DIM,
                              highlightthickness=1)
        log_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

        tk.Label(
            log_frame, text=" LOG", bg=BG_PANEL, fg=FG_MUTED, font=FONT_MONO_BOLD,
            anchor="w",
        ).pack(fill="x", padx=6, pady=(4, 0))

        self.log_text = tk.Text(
            log_frame,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_ACCENT,
            relief="flat",
            font=("Consolas", 9),
            wrap="word",
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text.tag_configure("error", foreground=FG_ERROR)
        self.log_text.tag_configure("accent", foreground=FG_ACCENT)

        # Results panel
        results_frame = tk.Frame(body, bg=BG_PANEL, highlightbackground=FG_ACCENT_DIM,
                                  highlightthickness=1, width=420)
        results_frame.pack(side="left", fill="both", expand=False)
        results_frame.pack_propagate(False)

        top_bar = tk.Frame(results_frame, bg=BG_PANEL)
        top_bar.pack(fill="x", padx=6, pady=(4, 0))

        tk.Label(
            top_bar, text="RESULTS", bg=BG_PANEL, fg=FG_MUTED, font=FONT_MONO_BOLD,
        ).pack(side="left")

        self.count_label = tk.Label(
            top_bar, text="0 emails", bg=BG_PANEL, fg=FG_ACCENT, font=FONT_MONO,
        )
        self.count_label.pack(side="right")

        columns = ("email", "source")
        self.tree = ttk.Treeview(
            results_frame, columns=columns, show="headings", selectmode="extended"
        )
        self.tree.heading("email", text="EMAIL")
        self.tree.heading("source", text="SOURCE URL")
        self.tree.column("email", width=170)
        self.tree.column("source", width=200)
        self.tree.pack(fill="both", expand=True, padx=6, pady=6)

        scrollbar = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        # Footer / actions
        footer = tk.Frame(self, bg=BG_MAIN)
        footer.pack(fill="x", padx=16, pady=(4, 14))

        ttk.Button(
            footer, text="EXPORT CSV", style="Accent.TButton", command=self.export_csv
        ).pack(side="right")

        ttk.Button(
            footer, text="COPY ALL", style="Dark.TButton", command=self.copy_all
        ).pack(side="right", padx=(0, 8))

        ttk.Button(
            footer, text="CLEAR", style="Dark.TButton", command=self.clear_results
        ).pack(side="right", padx=(0, 8))

    # ------------------------------------------
    # Logging helpers
    # ------------------------------------------

    def _append_log(self, message):
        self.log_text.configure(state="normal")
        tag = ()
        if message.startswith("[X]"):
            tag = ("error",)
        elif message.startswith("[+]"):
            tag = ("accent",)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------
    # Search lifecycle
    # ------------------------------------------

    def start_search(self):
        if self.worker and self.worker.is_alive():
            return

        query = self.query_var.get().strip()
        if not query:
            messagebox.showwarning("Empty query", "Enter a search query first.")
            return

        if not self.client:
            messagebox.showerror("No client", "Search client is not configured.")
            return

        self.clear_results()
        self.stop_event.clear()

        self.search_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._searching = True
        self.status_label.configure(fg=FG_ACCENT)
        self.progress.start(12)

        pages = max(1, int(self.pages_var.get()))
        deep_scan = self.deep_scan_var.get()

        self.worker = SearchWorker(
            self.client, query, pages, self.log_queue, self.result_queue, self.stop_event,
            deep_scan_pdfs=deep_scan,
        )
        self.worker.start()

    def stop_search(self):
        self.stop_event.set()
        self.stop_btn.configure(state="disabled")

    def _search_finished(self):
        self.search_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._searching = False
        self.status_label.configure(text="READY", fg=FG_MUTED)
        self.status_dot.configure(text="●", fg=FG_ACCENT_DIM)
        self.progress.stop()

    # ------------------------------------------
    # Queue polling (keeps UI thread-safe)
    # ------------------------------------------

    def _poll_queues(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass

        try:
            rows = self.result_queue.get_nowait()
            self._load_rows(rows)
            self._search_finished()
        except queue.Empty:
            pass

        self.after(100, self._poll_queues)

    def _load_rows(self, rows):
        # de-duplicate by email, keep first source seen
        seen = {}
        for row in rows:
            if row["email"] not in seen:
                seen[row["email"]] = row

        self.rows = list(seen.values())
        self.rows.sort(key=lambda r: r["email"])

        for row in self.rows:
            self.tree.insert("", "end", values=(row["email"], row["source_url"]))

        self.count_label.configure(text=f"{len(self.rows)} emails")

    # ------------------------------------------
    # Result actions
    # ------------------------------------------

    def clear_results(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = []
        self.count_label.configure(text="0 emails")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def copy_all(self):
        if not self.rows:
            messagebox.showinfo("Nothing to copy", "No results yet.")
            return
        text = "\n".join(r["email"] for r in self.rows)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._append_log(f"[+] Copied {len(self.rows)} emails to clipboard.")

    def export_csv(self):
        if not self.rows:
            messagebox.showinfo("Nothing to export", "No results yet.")
            return

        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile="emails.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not filename:
            return

        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["email", "source_title", "source_url"])
            for row in self.rows:
                writer.writerow([row["email"], row["source_title"], row["source_url"]])

        self._append_log(f"[+] Exported {len(self.rows)} emails to {filename}")
        messagebox.showinfo("Export complete", f"Saved {len(self.rows)} emails to:\n{filename}")


if __name__ == "__main__":
    app = EmailFinderApp()
    app.mainloop()