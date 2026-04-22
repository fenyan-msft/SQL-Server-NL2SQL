"""
Chat Window
Main application window built with the standard tkinter library.

Windows conventions honoured:
  • Enter / Return  — submit the current message
  • Ctrl+C          — copy selected text from the chat area
  • Ctrl+A          — select all chat text
  • Ctrl+L          — clear the conversation
  • Right-click     — context menu (Copy / Select All / Clear)
  • The chat area is read-only for editing but fully selectable / copyable.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

import speech_recognition as sr   # imported here for exception-type access

from agent.nl2sqlagents import AgentOrchestrator
from config import APP_HEIGHT, APP_TITLE, APP_WIDTH, FONT_FAMILY, FONT_MONO
from services.speech_service import SpeechService

# ── Colour palette (Windows 11-inspired) ──────────────────────────────────────
_C_BG          = "#FFFFFF"
_C_CHAT_BG     = "#FAFAFA"
_C_USER_NAME   = "#0078D4"   # Windows accent blue
_C_BOT_NAME    = "#107C10"   # Windows green
_C_SQL_NAME    = "#7A3600"   # warm brown for SQL responses
_C_ERROR       = "#C42B1C"   # Windows alert red
_C_SYSTEM      = "#767676"   # muted grey
_C_TRACE       = "#6B24A8"   # purple for method-call traces
_C_CODE_BG     = "#F3F2F1"   # light grey background for code
_C_BORDER      = "#D1D1D1"
_C_STATUS_BG   = "#F0F0F0"
_C_SEND_BG     = "#0078D4"
_C_SEND_FG     = "#FFFFFF"
_C_MIC_IDLE_BG = "#107C10"
_C_MIC_BUSY_BG = "#C42B1C"   # turns red while recording
_C_MIC_FG      = "#FFFFFF"


class ChatWindow:
    """Full-featured Tkinter chat window with LLM + SQL-Server back-end."""

    # ── Construction ─────────────────────────────────────────────────────────

    def __init__(self, person_id: int) -> None:
        self._person_id = person_id
        self.root = tk.Tk()
        self._configure_root()

        # Back-end services
        self._orchestrator = AgentOrchestrator(trace_callback=self._on_trace, person_id=person_id)
        self._speech       = SpeechService()

        # Mutable UI state flags (always read / written on the main thread)
        self._processing = False
        self._listening  = False
        self._speech_accumulated = ""

        # Build the interface top → bottom
        self._build_menu()
        self._build_chat_area()
        self._build_input_area()
        self._build_status_bar()
        self._setup_global_bindings()

        # Initial greeting
        self._append_system(
            "Welcome to AdventureWorks Cycles!\n"
            "• Type a question and press Enter (or click Send).\n"
            "• Click  🎤 Speak  to answer via the microphone.\n"
            "• Right-click or use Ctrl+C to copy any visible text."
        )
        self._update_status("Ready")
        self._input.focus_set()

    # ── Window setup ─────────────────────────────────────────────────────────

    def _configure_root(self) -> None:
        self.root.title(f"{APP_TITLE}  —  Person {self._person_id}")
        self.root.geometry(f"{APP_WIDTH}x{APP_HEIGHT}")
        self.root.minsize(600, 460)
        self.root.configure(bg=_C_BG)
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - APP_WIDTH)  // 2
        y = (self.root.winfo_screenheight() - APP_HEIGHT) // 2
        self.root.geometry(f"+{x}+{y}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Menu bar ─────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="New Chat",
            accelerator="Ctrl+N",
            command=self._on_new_chat,
        )
        file_menu.add_command(
            label="Clear Conversation",
            accelerator="Ctrl+L",
            command=self._prompt_clear,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(
            label="Copy",
            accelerator="Ctrl+C",
            command=self._copy_selection,
        )
        edit_menu.add_command(
            label="Select All",
            accelerator="Ctrl+A",
            command=self._select_all_chat,
        )
        menubar.add_cascade(label="Edit", menu=edit_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    # ── Chat display ─────────────────────────────────────────────────────────

    def _build_chat_area(self) -> None:
        frame = tk.Frame(self.root, bg=_C_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._chat = tk.Text(
            frame,
            yscrollcommand=scrollbar.set,
            state=tk.NORMAL,
            wrap=tk.WORD,
            font=(FONT_FAMILY, 10),
            bg=_C_CHAT_BG,
            fg="#1A1A1A",
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightbackground=_C_BORDER,
            cursor="xterm",
            spacing1=3,
            spacing3=3,
            padx=10,
            pady=8,
        )
        self._chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._chat.yview)

        self._configure_chat_tags()

        # Input-blocking and selection bindings
        self._chat.bind("<Key>",       self._block_key_input)
        self._chat.bind("<Control-c>", lambda _e: self._copy_selection())
        self._chat.bind("<Control-C>", lambda _e: self._copy_selection())
        self._chat.bind("<Control-a>", lambda _e: self._select_all_chat())
        self._chat.bind("<Control-A>", lambda _e: self._select_all_chat())
        self._chat.bind("<Button-3>",  self._show_context_menu)

    def _configure_chat_tags(self) -> None:
        f_normal = (FONT_FAMILY, 10)
        f_bold   = (FONT_FAMILY, 10, "bold")
        f_italic = (FONT_FAMILY,  9, "italic")
        f_code   = (FONT_MONO,    9)
        f_code_b = (FONT_MONO,    9, "bold")

        self._chat.tag_configure("user_name",   foreground=_C_USER_NAME, font=f_bold)
        self._chat.tag_configure("user_text",   foreground="#1A1A1A",    font=f_normal)
        self._chat.tag_configure("bot_name",    foreground=_C_BOT_NAME,  font=f_bold)
        self._chat.tag_configure("bot_text",    foreground="#1A1A1A",    font=f_normal)
        self._chat.tag_configure("sql_name",    foreground=_C_SQL_NAME,  font=f_bold)
        self._chat.tag_configure("sql_header",  foreground=_C_SQL_NAME,  font=f_code_b)
        self._chat.tag_configure("sql_code",    foreground="#5C1A00",    font=f_code,
                                                background=_C_CODE_BG)
        self._chat.tag_configure("table_code",  foreground="#1A1A1A",    font=f_code,
                                                background=_C_CODE_BG)
        self._chat.tag_configure("error_name",  foreground=_C_ERROR,     font=f_bold)
        self._chat.tag_configure("error_text",  foreground=_C_ERROR,     font=f_normal)
        self._chat.tag_configure("system_text", foreground=_C_SYSTEM,    font=f_italic)
        self._chat.tag_configure("trace_text",  foreground=_C_TRACE,     font=f_italic)
        self._chat.tag_configure("separator",   foreground=_C_BORDER)

        # Ensure the built-in selection highlight always renders on top of tags
        # that carry an explicit background colour (sql_code, table_code, etc.).
        self._chat.tag_configure("sel", background=_C_SEND_BG, foreground="white")
        self._chat.tag_raise("sel")

    @staticmethod
    def _block_key_input(event: tk.Event) -> str | None:
        """Block keystrokes that would modify the chat area; allow all others.

        Allowed:
          • Navigation keys (arrows, Home, End, Page Up/Down)
          • Modifier keys on their own (Shift, Ctrl, Alt)
          • Ctrl+C (copy) and Ctrl+A (select-all)
        Blocked:
          • Everything else (printable chars, Delete, BackSpace, Ctrl+V, Ctrl+X …)
        """
        _NAV = {
            "Left", "Right", "Up", "Down",
            "Home", "End", "Prior", "Next",   # Prior = Page Up, Next = Page Down
            "Shift_L", "Shift_R",
            "Control_L", "Control_R",
            "Alt_L", "Alt_R",
        }
        if event.keysym in _NAV:
            return None                        # let navigation / selection work
        if event.state & 0x0004:               # Ctrl held
            if event.keysym.lower() in ("c", "a"):
                return None                    # Ctrl+C / Ctrl+A pass through
            return "break"                     # block Ctrl+V, Ctrl+X, etc.
        return "break"                         # block typing, Delete, BackSpace …

    # ── Input area ───────────────────────────────────────────────────────────

    def _build_input_area(self) -> None:
        frame = tk.Frame(self.root, bg=_C_BG)
        frame.pack(fill=tk.X, padx=8, pady=6)

        # ── New Chat button ───────────────────────────────────────────────
        self._new_chat_btn = tk.Button(
            frame,
            text="＋ New Chat",
            width=10,
            font=(FONT_FAMILY, 10),
            bg="#F0F0F0",
            fg="#1A1A1A",
            activebackground="#D0D0D0",
            relief=tk.FLAT,
            cursor="hand2",
            command=self._on_new_chat,
        )
        self._new_chat_btn.pack(side=tk.LEFT, padx=(0, 6), ipady=5)

        # ── Microphone button ─────────────────────────────────────────────
        self._mic_btn = tk.Button(
            frame,
            text="🎤  Speak",
            width=9,
            font=(FONT_FAMILY, 10),
            bg=_C_MIC_IDLE_BG,
            fg=_C_MIC_FG,
            activebackground="#0B6A0B",
            activeforeground=_C_MIC_FG,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._start_listening,
        )
        self._mic_btn.pack(side=tk.LEFT, padx=(0, 6), ipady=5)

        if not self._speech.available:
            self._mic_btn.config(
                state=tk.DISABLED,
                text="🎤  N/A",
                bg="#A0A0A0",
            )

        # ── Text entry field ─────────────────────────────────────────────
        self._input_var = tk.StringVar()
        self._input = tk.Entry(
            frame,
            textvariable=self._input_var,
            font=(FONT_FAMILY, 10),
            bg="#FFFFFF",
            fg="#1A1A1A",
            insertbackground="#1A1A1A",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=_C_BORDER,
            highlightcolor=_C_USER_NAME,
        )
        self._input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)

        # ── Send button ───────────────────────────────────────────────────
        self._send_btn = tk.Button(
            frame,
            text="Send  ↵",
            width=9,
            font=(FONT_FAMILY, 10),
            bg=_C_SEND_BG,
            fg=_C_SEND_FG,
            activebackground="#005A9E",
            activeforeground=_C_SEND_FG,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._on_submit,
        )
        self._send_btn.pack(side=tk.LEFT, padx=(6, 0), ipady=5)

    # ── Status bar ───────────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self.root, bg=_C_STATUS_BG, height=22)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)

        self._status_var = tk.StringVar(value="Ready")
        tk.Label(
            bar,
            textvariable=self._status_var,
            bg=_C_STATUS_BG,
            fg=_C_SYSTEM,
            font=(FONT_FAMILY, 9),
            anchor=tk.W,
        ).pack(side=tk.LEFT, padx=8)

    # ── Global key bindings ──────────────────────────────────────────────────

    def _setup_global_bindings(self) -> None:
        self.root.bind("<Control-n>", lambda _e: self._on_new_chat())
        self.root.bind("<Control-N>", lambda _e: self._on_new_chat())
        self.root.bind("<Control-l>", lambda _e: self._prompt_clear())
        self.root.bind("<Control-L>", lambda _e: self._prompt_clear())
        self._input.bind("<Return>",   lambda _e: self._on_submit())
        self._input.bind("<KP_Enter>", lambda _e: self._on_submit())   # numpad Enter

    # ── Submit (type) ─────────────────────────────────────────────────────────

    def _on_submit(self) -> None:
        text = self._input_var.get().strip()
        if not text or self._processing or self._listening:
            return

        self._input_var.set("")
        self._set_busy(True, "Processing…")
        self._append_user(text)

        def _worker(prompt: str) -> None:
            try:
                result = self._orchestrator.process(prompt)
            except Exception as exc:
                result = f"[Error]\n{exc}"
            self.root.after(0, lambda: self._on_response(result))

        threading.Thread(target=_worker, args=(text,), daemon=True).start()

    def _on_response(self, response: str) -> None:
        self._append_bot(response)
        self._set_busy(False, "Ready")
        self._input.focus_set()

    # ── Microphone ────────────────────────────────────────────────────────────

    def _start_listening(self) -> None:
        if self._processing or self._listening:
            return

        self._listening = True
        self._speech_accumulated = ""
        self._mic_btn.config(
            state=tk.NORMAL,
            text="⏹  Stop",
            bg=_C_MIC_BUSY_BG,
            command=self._stop_listening,
        )
        self._send_btn.config(state=tk.DISABLED)
        self._input.config(state=tk.NORMAL)
        self._update_status("Listening… speak now, click ⏹ Stop when done")

        try:
            self._speech.start_continuous(
                on_recognizing=lambda t: self.root.after(0, lambda p=t: self._on_partial(p)),
                on_recognized =lambda t: self.root.after(0, lambda u=t: self._on_utterance(u)),
                on_error      =lambda e: self.root.after(0, lambda m=e: self._on_speech_error(m)),
            )
        except Exception as exc:
            self._on_speech_error(str(exc))

    def _stop_listening(self) -> None:
        self._speech.stop_continuous()
        text = self._speech_accumulated.strip()
        self._listening = False
        self._restore_inputs()
        if text:
            self._input_var.set(text)
            self._input.icursor(tk.END)
            self._input.focus_set()
            self._update_status("Ready — press Enter or click Send")
        else:
            self._update_status("Ready")

    def _on_partial(self, partial: str) -> None:
        display = (self._speech_accumulated + " " + partial).strip()
        self._input_var.set(display)
        self._input.icursor(tk.END)

    def _on_utterance(self, text: str) -> None:
        self._speech_accumulated = (self._speech_accumulated + " " + text).strip()
        self._input_var.set(self._speech_accumulated)
        self._input.icursor(tk.END)

    def _on_speech_result(self, text: str) -> None:
        """Fallback handler for non-Azure / batch recognition."""
        self._listening = False
        self._restore_inputs()
        self._input_var.set(text)
        self._input.icursor(tk.END)
        self._input.focus_set()
        self._update_status("Ready — press Enter or click Send")

    def _on_speech_error(self, message: str) -> None:
        self._listening = False
        self._restore_inputs()
        self._append_system(f"Microphone: {message}")
        self._update_status("Ready")

    def _restore_inputs(self) -> None:
        self._input.config(state=tk.NORMAL)
        self._send_btn.config(state=tk.NORMAL)
        if self._speech.available:
            self._mic_btn.config(
                state=tk.NORMAL,
                text="🎤  Speak",
                bg=_C_MIC_IDLE_BG,
                command=self._start_listening,
            )

    # ── Chat insertion helpers ────────────────────────────────────────────────

    def _insert(self, text: str, tag: str | None = None) -> None:
        """Append *text* to the chat widget."""
        if tag:
            self._chat.insert(tk.END, text, tag)
        else:
            self._chat.insert(tk.END, text)

    def _append_separator(self) -> None:
        self._insert("─" * 72 + "\n", "separator")

    def _append_user(self, text: str) -> None:
        self._append_separator()
        self._insert("You\n", "user_name")
        self._insert(text + "\n", "user_text")
        self._chat.see(tk.END)

    def _append_bot(self, response: str) -> None:
        """Render the agent response with appropriate formatting."""
        if "[Generated T-SQL]" in response:
            self._insert("Assistant  [SQL result]\n", "sql_name")
            self._render_sql_response(response)
        elif (
            response.startswith("[SQL Error]")
            or response.startswith("[Vector Search Error]")
            or response.startswith("[LLM Error]")
            or response.startswith("[Error]")
        ):
            self._insert("Assistant  [Error]\n", "error_name")
            self._insert(response.strip() + "\n", "error_text")
        else:
            self._insert("Assistant\n", "bot_name")
            self._render_bot_text(response.strip())
        self._chat.see(tk.END)

    def _render_bot_text(self, text: str) -> None:
        """Render bot text, switching to monospace for pipe-table lines."""
        buf_text:  list[str] = []
        buf_table: list[str] = []

        def _flush_text() -> None:
            if buf_text:
                self._insert("\n".join(buf_text) + "\n", "bot_text")
                buf_text.clear()

        def _flush_table() -> None:
            if buf_table:
                self._insert("\n".join(buf_table) + "\n", "table_code")
                buf_table.clear()

        for line in text.splitlines():
            if line.startswith("|"):
                _flush_text()
                buf_table.append(line)
            else:
                _flush_table()
                buf_text.append(line)

        _flush_text()
        _flush_table()

    def _render_sql_response(self, text: str) -> None:
        """
        Parse the structured SQL response and render each section with its
        own visual style.

        Expected format (produced by AgentOrchestrator._format_sql_result):
            [Generated T-SQL]
            <t-sql query>

            <results table>
            (<N> rows returned)
        """
        marker = "[Generated T-SQL]\n"
        if marker not in text:
            self._insert(text.strip() + "\n", "sql_code")
            return

        before, rest = text.split(marker, 1)
        if before.strip():
            self._insert(before.strip() + "\n", "bot_text")

        # Section header
        self._insert("[Generated T-SQL]\n", "sql_header")

        # Split on first blank line separating the query from the results
        if "\n\n" in rest:
            sql_query, results = rest.split("\n\n", 1)
            self._insert(sql_query.strip() + "\n\n", "sql_code")
            self._insert(results.strip()    + "\n",  "table_code")
        else:
            self._insert(rest.strip() + "\n", "sql_code")

    def _append_system(self, text: str) -> None:
        self._insert(text.strip() + "\n", "system_text")
        self._chat.see(tk.END)

    def _append_trace(self, step: str) -> None:
        """Append a method-call trace line in a distinct style.

        If *step* contains a newline, everything before it is the label and
        everything after is rendered as a code block (e.g. a generated query).
        """
        label, _, code = step.partition("\n")
        self._insert(f"  \u27f6 {label}\n", "trace_text")
        if code.strip():
            self._insert(code.strip() + "\n", "sql_code")
        self._chat.see(tk.END)

    def _on_trace(self, step: str) -> None:
        """Thread-safe trace callback: schedule _append_trace on the main thread."""
        self.root.after(0, lambda s=step: self._append_trace(s))

    # ── UI state helpers ─────────────────────────────────────────────────────

    def _set_busy(self, busy: bool, status: str) -> None:
        self._processing = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self._input.config(state=state)
        self._send_btn.config(state=state)
        self._new_chat_btn.config(state=state)
        if self._speech.available:
            self._mic_btn.config(state=state)
        self._update_status(status)

    def _update_status(self, message: str) -> None:
        self._status_var.set(message)

    # ── Edit / clipboard actions ─────────────────────────────────────────────

    def _copy_selection(self) -> None:
        try:
            selected = self._chat.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(selected)
        except tk.TclError:
            pass   # nothing selected — silently ignore

    def _select_all_chat(self) -> None:
        self._chat.tag_add(tk.SEL, "1.0", tk.END)
        self._chat.focus_set()

    # ── Context menu (right-click) ────────────────────────────────────────────

    def _show_context_menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(
            label="Copy",
            accelerator="Ctrl+C",
            command=self._copy_selection,
        )
        menu.add_command(
            label="Select All",
            accelerator="Ctrl+A",
            command=self._select_all_chat,
        )
        menu.add_separator()
        menu.add_command(label="New Chat", command=self._on_new_chat)
        menu.add_command(label="Clear Conversation…", command=self._prompt_clear)
        menu.tk_popup(event.x_root, event.y_root)

    # ── New chat ──────────────────────────────────────────────────────────────

    def _on_new_chat(self) -> None:
        if self._processing or self._listening:
            return
        self._chat.delete("1.0", tk.END)
        self._orchestrator.clear_conversation()
        self._append_system(
            f"New chat started  (Person ID: {self._person_id}).\n"
            "• Type a question and press Enter (or click Send).\n"
            "• Click  \U0001f3a4 Speak  to answer via the microphone."
        )
        self._input_var.set("")
        self._input.focus_set()
        self._update_status("Ready")

    # ── Clear conversation ────────────────────────────────────────────────────

    def _prompt_clear(self) -> None:
        if messagebox.askyesno(
            title="Clear Conversation",
            message="Clear all messages and reset the conversation history?",
            icon=messagebox.QUESTION,
        ):
            self._chat.delete("1.0", tk.END)
            self._orchestrator.clear_conversation()
            self._append_system("Conversation cleared. Start a new question below.")
            self._input.focus_set()

    # ── About ─────────────────────────────────────────────────────────────────

    def _show_about(self) -> None:
        messagebox.showinfo(
            title=f"About {APP_TITLE}",
            message=(
                f"{APP_TITLE}\n\n"
                "Ask questions in plain English.\n"
                "The agent automatically routes:\n"
                "  • General questions → LLM\n"
                "  • Data / reporting questions → SQL Server\n\n"
                "Configure your endpoints and credentials in config.py."
            ),
        )

    # ── Close ─────────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        self.root.destroy()

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        self.root.mainloop()
