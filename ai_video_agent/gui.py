from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .agent import EditRequest, run_edit
from .image_agent import ImageRequest, run_image_generation
from .llm import LLMConfig, OpenAICompatibleClient


BG = "#f4f7f8"
PANEL = "#ffffff"
PANEL_2 = "#e9eff2"
FIELD = "#fbfcfc"
TEXT = "#17212b"
MUTED = "#5d6872"
SUBTLE = "#8a97a1"
ACCENT = "#516c84"
ACCENT_2 = "#40566a"
BORDER = "#cad8df"
FOCUS = "#7d95a8"
OK = "#2f855a"
WARN = "#a86719"
BAD = "#c2413b"


IMAGE_MODES = {
    "文生图": "text_to_image",
    "参考图风格迁移": "style_reference",
    "保留内容改风格": "edit_style",
}


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        master,
        text: str,
        command=None,
        width: int = 120,
        height: int = 40,
        variant: str = "primary",
    ) -> None:
        self.text = text
        self.command = command
        self.variant = variant
        self.enabled = True
        self.radius = 18
        self.palette = {
            "primary": {
                "bg": ACCENT,
                "hover": "#5f7c95",
                "active": ACCENT_2,
                "disabled": "#c8d1d7",
                "fg": "#ffffff",
            },
            "ghost": {
                "bg": "#eef3f5",
                "hover": "#e3ebef",
                "active": "#d7e2e8",
                "disabled": "#eef1f3",
                "fg": TEXT,
            },
        }[variant]
        try:
            parent_bg = master.cget("background")
        except tk.TclError:
            parent_bg = PANEL
        super().__init__(
            master,
            width=width,
            height=height,
            bg=parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._fill = self.palette["bg"]
        self.bind("<Configure>", lambda _event: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._redraw()

    def configure(self, cnf=None, **kwargs):  # type: ignore[override]
        cnf = cnf or {}
        kwargs.update(cnf)
        if "state" in kwargs:
            self.enabled = kwargs.pop("state") != "disabled"
            self.configure(cursor="hand2" if self.enabled else "arrow")
            self._fill = self.palette["bg"] if self.enabled else self.palette["disabled"]
            self._redraw()
        if "text" in kwargs:
            self.text = str(kwargs.pop("text"))
            self._redraw()
        if kwargs:
            return super().configure(**kwargs)
        return None

    config = configure

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=16, **kwargs)

    def _redraw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), int(self["width"]))
        height = max(self.winfo_height(), int(self["height"]))
        fill = self._fill if self.enabled else self.palette["disabled"]
        self._rounded_rect(1, 1, width - 1, height - 1, min(self.radius, height // 2), fill=fill, outline="")
        self.create_text(
            width // 2,
            height // 2,
            text=self.text,
            fill=self.palette["fg"] if self.enabled else MUTED,
            font=("Microsoft YaHei UI", 10, "bold"),
        )

    def _on_enter(self, _event) -> None:
        if self.enabled:
            self._fill = self.palette["hover"]
            self._redraw()

    def _on_leave(self, _event) -> None:
        if self.enabled:
            self._fill = self.palette["bg"]
            self._redraw()

    def _on_press(self, _event) -> None:
        if self.enabled:
            self._fill = self.palette["active"]
            self._redraw()

    def _on_release(self, _event) -> None:
        if self.enabled:
            self._fill = self.palette["hover"]
            self._redraw()
            if self.command:
                self.command()


class RoundedPanel(tk.Canvas):
    def __init__(
        self,
        master,
        fill: str = PANEL,
        radius: int = 24,
        padding: int = 18,
        auto_height: bool = True,
    ) -> None:
        try:
            parent_bg = master.cget("background")
        except tk.TclError:
            parent_bg = BG
        super().__init__(master, bg=parent_bg, highlightthickness=0, bd=0)
        self.fill = fill
        self.radius = radius
        self.padding = padding
        self.auto_height = auto_height
        self.body = tk.Frame(self, bg=fill)
        self._window = self.create_window(padding, padding, window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body_configure)
        self.bind("<Configure>", self._redraw)

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=18, **kwargs)

    def _on_body_configure(self, _event=None) -> None:
        if self.auto_height:
            next_height = self.body.winfo_reqheight() + self.padding * 2
            if next_height > 1:
                self.configure(height=next_height)
        self._redraw()

    def _redraw(self, _event=None) -> None:
        width = max(self.winfo_width(), self.body.winfo_reqwidth() + self.padding * 2)
        base_height = self.body.winfo_reqheight() + self.padding * 2
        height = max(self.winfo_height(), base_height if self.auto_height else 1)
        self.delete("surface")
        self._rounded_rect(1, 1, width - 1, height - 1, self.radius, fill=self.fill, outline="", tags="surface")
        self.tag_lower("surface")
        self.itemconfigure(self._window, width=max(1, width - self.padding * 2))
        if not self.auto_height:
            self.itemconfigure(self._window, height=max(1, height - self.padding * 2))


class RoundedInput(tk.Canvas):
    def __init__(self, master, textvariable: tk.StringVar, show: str = "", height: int = 40) -> None:
        try:
            parent_bg = master.cget("background")
        except tk.TclError:
            parent_bg = PANEL
        super().__init__(master, height=height, bg=parent_bg, highlightthickness=0, bd=0)
        self.height = height
        self.focused = False
        self.entry = tk.Entry(
            self,
            textvariable=textvariable,
            show=show,
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            selectbackground="#dce9ef",
            selectforeground=TEXT,
            font=("Microsoft YaHei UI", 10),
        )
        self._window = self.create_window(14, height // 2, window=self.entry, anchor="w")
        self.bind("<Configure>", self._redraw)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self._redraw()

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=18, **kwargs)

    def _on_focus_in(self, _event) -> None:
        self.focused = True
        self._redraw()

    def _on_focus_out(self, _event) -> None:
        self.focused = False
        self._redraw()

    def _redraw(self, _event=None) -> None:
        width = max(self.winfo_width(), 160)
        self.delete("surface")
        self._rounded_rect(
            1,
            1,
            width - 1,
            self.height - 1,
            self.height // 2,
            fill=FIELD,
            outline=FOCUS if self.focused else BORDER,
            width=1.4 if self.focused else 1,
            tags="surface",
        )
        self.tag_lower("surface")
        self.itemconfigure(self._window, width=max(1, width - 28), height=self.height - 12)


class RoundedSelect(tk.Canvas):
    def __init__(self, master, textvariable: tk.StringVar, values: tuple[str, ...], height: int = 40) -> None:
        try:
            parent_bg = master.cget("background")
        except tk.TclError:
            parent_bg = PANEL
        super().__init__(master, height=height, bg=parent_bg, highlightthickness=0, bd=0, cursor="hand2")
        self.variable = textvariable
        self.values = values
        self.height = height
        self.hovered = False
        self.menu = tk.Menu(
            self,
            tearoff=0,
            bg=PANEL,
            fg=TEXT,
            activebackground="#e6eff3",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            font=("Microsoft YaHei UI", 10),
        )
        for value in values:
            self.menu.add_command(label=value, command=lambda item=value: self.variable.set(item))
        self.variable.trace_add("write", lambda *_args: self._redraw())
        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._open_menu)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._redraw()

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=18, **kwargs)

    def _display_text(self) -> str:
        value = self.variable.get()
        return value if len(value) <= 34 else value[:31] + "..."

    def _open_menu(self, event) -> None:
        self.menu.post(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())

    def _on_enter(self, _event) -> None:
        self.hovered = True
        self._redraw()

    def _on_leave(self, _event) -> None:
        self.hovered = False
        self._redraw()

    def _redraw(self, _event=None) -> None:
        width = max(self.winfo_width(), 160)
        self.delete("all")
        self._rounded_rect(
            1,
            1,
            width - 1,
            self.height - 1,
            self.height // 2,
            fill="#ffffff" if self.hovered else FIELD,
            outline=FOCUS if self.hovered else BORDER,
            width=1.3 if self.hovered else 1,
        )
        self.create_text(
            14,
            self.height // 2,
            text=self._display_text(),
            anchor="w",
            fill=TEXT,
            font=("Microsoft YaHei UI", 10),
        )
        self.create_text(
            width - 18,
            self.height // 2,
            text="v",
            anchor="center",
            fill=ACCENT,
            font=("Microsoft YaHei UI", 10, "bold"),
        )


class RoundedSpinbox(tk.Canvas):
    def __init__(self, master, from_: int, to: int, textvariable: tk.IntVar, height: int = 40) -> None:
        try:
            parent_bg = master.cget("background")
        except tk.TclError:
            parent_bg = PANEL
        super().__init__(master, height=height, bg=parent_bg, highlightthickness=0, bd=0)
        self.height = height
        self.focused = False
        self.spinbox = tk.Spinbox(
            self,
            from_=from_,
            to=to,
            textvariable=textvariable,
            bg=FIELD,
            fg=TEXT,
            buttonbackground=FIELD,
            relief="flat",
            bd=0,
            highlightthickness=0,
            insertbackground=TEXT,
            font=("Microsoft YaHei UI", 10),
        )
        self._window = self.create_window(14, height // 2, window=self.spinbox, anchor="w")
        self.bind("<Configure>", self._redraw)
        self.spinbox.bind("<FocusIn>", self._on_focus_in)
        self.spinbox.bind("<FocusOut>", self._on_focus_out)
        self._redraw()

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=18, **kwargs)

    def _on_focus_in(self, _event) -> None:
        self.focused = True
        self._redraw()

    def _on_focus_out(self, _event) -> None:
        self.focused = False
        self._redraw()

    def _redraw(self, _event=None) -> None:
        width = max(self.winfo_width(), 160)
        self.delete("surface")
        self._rounded_rect(
            1,
            1,
            width - 1,
            self.height - 1,
            self.height // 2,
            fill=FIELD,
            outline=FOCUS if self.focused else BORDER,
            width=1.4 if self.focused else 1,
            tags="surface",
        )
        self.tag_lower("surface")
        self.itemconfigure(self._window, width=max(1, width - 28), height=self.height - 12)


class RoundedTextBox(tk.Canvas):
    def __init__(self, master, height: int, font: tuple[str, int] | tuple[str, int, str]) -> None:
        try:
            parent_bg = master.cget("background")
        except tk.TclError:
            parent_bg = PANEL
        super().__init__(master, height=height, bg=parent_bg, highlightthickness=0, bd=0)
        self.box_height = height
        self.focused = False
        self.text = tk.Text(
            self,
            wrap="word",
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=14,
            pady=12,
            font=font,
        )
        self._window = self.create_window(2, 2, window=self.text, anchor="nw")
        self.bind("<Configure>", self._redraw)
        self.text.bind("<FocusIn>", self._on_focus_in)
        self.text.bind("<FocusOut>", self._on_focus_out)
        self._redraw()

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=18, **kwargs)

    def _on_focus_in(self, _event) -> None:
        self.focused = True
        self._redraw()

    def _on_focus_out(self, _event) -> None:
        self.focused = False
        self._redraw()

    def _redraw(self, _event=None) -> None:
        width = max(self.winfo_width(), 180)
        height = max(self.winfo_height(), self.box_height)
        self.delete("surface")
        self._rounded_rect(
            1,
            1,
            width - 1,
            height - 1,
            18,
            fill=FIELD,
            outline=FOCUS if self.focused else BORDER,
            width=1.4 if self.focused else 1,
            tags="surface",
        )
        self.tag_lower("surface")
        self.itemconfigure(self._window, width=max(1, width - 4), height=max(1, height - 4))


class VideoAgentApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AI Video Agent")
        self.geometry("1180x780")
        self.minsize(980, 680)
        self.configure(bg=BG)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.base_url = tk.StringVar(value="https://api.deepseek.com/v1")
        self.api_key = tk.StringVar()
        self.model = tk.StringVar(value="deepseek-chat")
        self.api_validated = False

        self.media_dir = tk.StringVar()
        self.music_dir = tk.StringVar()
        self.output_dir = tk.StringVar(value=str((Path.cwd() / "outputs" / "rough_cuts").resolve()))
        self.output_name = tk.StringVar(value="ai_auto_cut")
        self.aspect_ratio = tk.StringVar(value="竖屏 9:16")
        self.target_duration = tk.IntVar(value=30)
        self.prefer_davinci = tk.BooleanVar(value=True)
        self.enable_algorithm = tk.BooleanVar(value=True)

        self.image_mode = tk.StringVar(value="文生图")
        self.image_api_key = tk.StringVar()
        self.image_model = tk.StringVar()
        self.reference_image = tk.StringVar()
        self.style_reference_image = tk.StringVar()
        self.content_image = tk.StringVar()
        self.image_output_dir = tk.StringVar(value=str((Path.cwd() / "outputs" / "images").resolve()))
        self.image_output_name = tk.StringVar(value="ai_image")
        self.image_size = tk.StringVar(value="1024x1024")
        self.image_count = tk.IntVar(value=1)
        self.image_steps = tk.IntVar(value=25)
        self.image_seed = tk.IntVar(value=42)
        self.content_strength = tk.DoubleVar(value=62)
        self.style_strength = tk.DoubleVar(value=60)
        self.image_smart_prompt = tk.BooleanVar(value=True)

        self._setup_style()
        self._build_ui()
        self.image_mode.trace_add("write", self._on_image_mode_changed)
        self.after(150, self._drain_logs)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, font=("Microsoft YaHei UI", 10))
        style.configure("Root.TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel2.TFrame", background=PANEL_2)
        style.configure("Line.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Help.TLabel", background=PANEL, foreground=SUBTLE, font=("Microsoft YaHei UI", 9))
        style.configure("Section.TLabel", background=PANEL, foreground=ACCENT, font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 24, "bold"))
        style.configure("Accent.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 10))
        style.configure("CardTitle.TLabel", background=PANEL, foreground=TEXT, font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("Status.TLabel", background=PANEL_2, foreground=ACCENT, font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Bar.TLabel", background=PANEL_2, foreground=MUTED)
        style.configure(
            "TEntry",
            fieldbackground=FIELD,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor="#d7e1e6",
            lightcolor="#d7e1e6",
            darkcolor="#d7e1e6",
            borderwidth=1,
            padding=(12, 9),
        )
        style.map(
            "TEntry",
            fieldbackground=[("focus", "#ffffff")],
            bordercolor=[("focus", ACCENT)],
            lightcolor=[("focus", ACCENT)],
        )
        style.configure(
            "TCombobox",
            fieldbackground=FIELD,
            background=FIELD,
            foreground=TEXT,
            arrowcolor=ACCENT,
            bordercolor="#d7e1e6",
            lightcolor="#d7e1e6",
            darkcolor="#d7e1e6",
            borderwidth=1,
            padding=(12, 9),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD), ("focus", "#ffffff")],
            selectbackground=[("readonly", FIELD)],
            bordercolor=[("focus", ACCENT)],
        )
        style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, bordercolor="#d7e1e6", padding=(12, 9))
        style.configure(
            "Primary.TButton",
            background=ACCENT,
            foreground="#ffffff",
            borderwidth=0,
            padding=(18, 11),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map("Primary.TButton", background=[("active", "#5f7c95"), ("disabled", "#c8d1d7")])
        style.configure("Ghost.TButton", background="#eef3f5", foreground=TEXT, borderwidth=0, padding=(14, 9))
        style.map("Ghost.TButton", background=[("active", "#e3ebef"), ("disabled", "#eef1f3")])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", TEXT)])
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background="#e7eef2", foreground=MUTED, padding=(20, 10), borderwidth=0)
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL), ("!selected", "#e7eef2")],
            foreground=[("selected", TEXT), ("!selected", MUTED)],
            padding=[("selected", (34, 15)), ("!selected", (20, 10))],
        )
        style.configure(
            "Vertical.TScrollbar",
            background="#d2dde3",
            troughcolor=PANEL,
            bordercolor=PANEL,
            arrowcolor=SUBTLE,
            lightcolor=PANEL,
            darkcolor=PANEL,
            width=10,
        )
        style.map("Vertical.TScrollbar", background=[("active", "#bacbd5")], arrowcolor=[("active", ACCENT)])

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, style="Root.TFrame", padding=24)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(2, weight=0)
        root.rowconfigure(3, weight=0)

        self._build_header(root)

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self.video_tab = ttk.Frame(self.notebook, style="Root.TFrame", padding=(0, 18, 0, 0))
        self.image_tab = ttk.Frame(self.notebook, style="Root.TFrame", padding=(0, 18, 0, 0))
        self.notebook.add(self.video_tab, text="视频剪辑")
        self.notebook.add(self.image_tab, text="图片生成")
        self._build_video_tab(self.video_tab)
        self._build_image_tab(self.image_tab)

        self._build_log_card(root)
        self._build_action_bar(root)

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="AI Video Agent", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="本地创作工作台，视频剪辑与图像生成在同一个安静、可控的界面里完成。",
            style="Accent.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.api_status = ttk.Label(header, text="剪辑 API 未验证", style="Status.TLabel", padding=(12, 8))
        self.api_status.grid(row=0, column=1, rowspan=2, sticky="e")

    def _build_video_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        left_shell, left = self._scrollable_panel(parent, width=430)
        left_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        right = ttk.Frame(parent, style="Root.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self._build_model_card(left)
        self._build_video_settings_card(left)
        self._build_video_prompt_card(right)

    def _build_model_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "剪辑大模型")
        self._field(card, "Base URL", self.base_url, 1)
        self._field(card, "API Key", self.api_key, 3, show="*")
        self._field(card, "模型", self.model, 5)
        self.validate_button = RoundedButton(card, text="验证剪辑 API", command=self.validate_api, width=320, height=42)
        self.validate_button.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(
            card,
            text="DeepSeek 示例：https://api.deepseek.com/v1 + deepseek-chat。这里主要用于理解剪辑需求和生成脚本。",
            style="PanelMuted.TLabel",
            wraplength=300,
        ).grid(row=8, column=0, sticky="w", pady=(10, 0))

    def _build_video_settings_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "视频任务")
        self._path_field(card, "素材文件夹", self.media_dir, 1, self.choose_media_dir)
        self._path_field(card, "BGM 文件夹", self.music_dir, 3, self.choose_music_dir)
        self._path_field(card, "输出文件夹", self.output_dir, 5, self.choose_output_dir)
        self._field(card, "输出名称", self.output_name, 7)

        row = 9
        self._choice_field(card, "画幅", self.aspect_ratio, ("竖屏 9:16", "横屏 16:9", "方形 1:1"), row)

        ttk.Label(card, text="目标时长（秒）", style="PanelMuted.TLabel").grid(row=row + 2, column=0, sticky="w", pady=(10, 4))
        RoundedSpinbox(card, from_=5, to=600, textvariable=self.target_duration).grid(row=row + 3, column=0, sticky="ew")

        ttk.Checkbutton(card, text="优先 DaVinci，失败后 FFmpeg", variable=self.prefer_davinci).grid(row=row + 4, column=0, sticky="w", pady=(12, 0))
        ttk.Checkbutton(card, text="启用算法优化（清晰度/运动/音频/高光）", variable=self.enable_algorithm).grid(
            row=row + 5, column=0, sticky="w", pady=(8, 0)
        )

    def _build_video_prompt_card(self, parent: ttk.Frame) -> None:
        surface = RoundedPanel(parent, fill=PANEL, radius=28, padding=22, auto_height=False)
        surface.grid(row=0, column=0, sticky="nsew")
        card = surface.body
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)
        card.rowconfigure(4, weight=1)
        card.rowconfigure(6, weight=1)
        ttk.Label(card, text="剪辑指令", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            card,
            text="输入风格、关键帧偏好和重点内容。算法会先分析素材，大模型再做导演决策。",
            style="PanelMuted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))
        self.style_text = self._text_area(card, 2, "视频风格")
        self.style_text.insert("1.0", "干净、有节奏、有轻微高级感；开头 3 秒抓人，中段突出重点，结尾收束。")
        self.keyframe_text = self._text_area(card, 4, "关键帧补充")
        self.keyframe_text.insert("1.0", "优先选择主体清晰、光线好、动作明确的镜头；避开明显抖动和无意义空镜。")
        self.focus_text = self._text_area(card, 6, "重点剪辑补充")
        self.focus_text.insert("1.0", "重点内容多停留一点，普通过渡镜头快切；需要字幕总结每个段落。")

    def _build_image_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        left_shell, left = self._scrollable_panel(parent, width=430)
        left_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        right = ttk.Frame(parent, style="Root.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self._build_image_settings_card(left)
        self._build_image_prompt_card(right)

    def _build_image_settings_card(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "图片生成")
        self._section_label(card, "生成方式", 1)
        self._choice_field(card, "模式", self.image_mode, tuple(IMAGE_MODES), 2)
        self.image_mode_hint = ttk.Label(card, text="", style="Help.TLabel", wraplength=344)
        self.image_mode_hint.grid(row=4, column=0, sticky="w", pady=(6, 2))

        self._section_label(card, "本地模型", 6)
        self._field(card, "基础模型 ID / 本地路径（选填）", self.image_model, 7)
        self._hint(card, "留空默认使用 SDXL base；首次运行会从 Hugging Face 下载模型。", 9)
        self._field(card, "DashScope API Key（选填）", self.image_api_key, 10, show="*")
        ttk.Checkbutton(card, text="启用智能提示词与风格分析", variable=self.image_smart_prompt).grid(
            row=12, column=0, sticky="w", pady=(10, 0)
        )
        self._hint(card, "不填 Key 也能生成；填写后会用 Qwen-VL 分析风格图，并把中文需求改写成 SDXL 英文提示词。", 13)

        self._section_label(card, "素材与输出", 15)
        self._path_file_field(card, "风格参考图", self.style_reference_image, 16, self.choose_style_reference_image)
        self._path_file_field(card, "内容图片", self.content_image, 18, self.choose_content_image)
        self._hint(card, "文生图可只填提示词；参考图风格迁移需要同时填写风格参考图和内容图片。", 20)
        self._path_field(card, "输出文件夹", self.image_output_dir, 21, self.choose_image_output_dir)
        self._field(card, "输出名称", self.image_output_name, 23)

        self._section_label(card, "生成参数", 25)
        self._choice_field(card, "尺寸", self.image_size, ("1024x1024", "1024x1536", "1536x1024"), 26)
        ttk.Label(card, text="数量", style="PanelMuted.TLabel").grid(row=28, column=0, sticky="w", pady=(10, 4))
        RoundedSpinbox(card, from_=1, to=4, textvariable=self.image_count).grid(row=29, column=0, sticky="ew")
        ttk.Label(card, text="采样步数", style="PanelMuted.TLabel").grid(row=30, column=0, sticky="w", pady=(10, 4))
        RoundedSpinbox(card, from_=10, to=60, textvariable=self.image_steps).grid(row=31, column=0, sticky="ew")
        ttk.Label(card, text="Seed", style="PanelMuted.TLabel").grid(row=32, column=0, sticky="w", pady=(10, 4))
        RoundedSpinbox(card, from_=0, to=2147483647, textvariable=self.image_seed).grid(row=33, column=0, sticky="ew")
        self._scale_field(card, "重绘强度", self.content_strength, 34)
        self._scale_field(card, "风格注入强度", self.style_strength, 36)
        self._on_image_mode_changed()

    def _build_image_prompt_card(self, parent: ttk.Frame) -> None:
        surface = RoundedPanel(parent, fill=PANEL, radius=28, padding=22, auto_height=False)
        surface.grid(row=0, column=0, sticky="nsew")
        card = surface.body
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)
        card.rowconfigure(5, weight=1)
        ttk.Label(card, text="图片提示词", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            card,
            text="文生图直接写画面；风格迁移会用内容图保持结构，用参考图注入画作风格。",
            style="PanelMuted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))
        prompt_box = RoundedTextBox(card, height=240, font=("Microsoft YaHei UI", 11))
        prompt_box.grid(row=2, column=0, sticky="nsew")
        self.image_prompt_text = prompt_box.text
        self.image_prompt_text.insert("1.0", "一幅有电影感的未来城市夜景，冷暖色对比，细节丰富，构图高级。")

        tools = tk.Frame(card, bg=PANEL)
        tools.grid(row=3, column=0, sticky="ew", pady=(14, 4))
        tools.columnconfigure(0, weight=1)
        ttk.Label(tools, text="风格分析 / 补充", style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.analyze_style_button = RoundedButton(
            tools,
            text="分析参考图",
            command=self.start_style_analysis,
            width=112,
            height=38,
            variant="ghost",
        )
        self.analyze_style_button.grid(row=0, column=1, sticky="e")

        style_box = RoundedTextBox(card, height=140, font=("Microsoft YaHei UI", 10))
        style_box.grid(row=5, column=0, sticky="nsew")
        self.style_analysis_text = style_box.text

    def _build_log_card(self, parent: ttk.Frame) -> None:
        surface = RoundedPanel(parent, fill=PANEL, radius=24, padding=14)
        surface.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        card = surface.body
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="运行日志", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        log_box = RoundedTextBox(card, height=126, font=("Consolas", 10))
        log_box.grid(row=1, column=0, sticky="ew")
        self.log_text = log_box.text
        self.log_text.configure(state="disabled")

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        surface = RoundedPanel(parent, fill=PANEL_2, radius=24, padding=14)
        surface.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        bar = surface.body
        bar.columnconfigure(0, weight=1)
        ttk.Label(
            bar,
            text="视频会输出成片、脚本、字幕和 timeline；图片会输出到你选择的图片文件夹。",
            style="Bar.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.run_video_button = RoundedButton(bar, text="剪辑视频", command=self.start_video_edit, width=112, height=42)
        self.run_video_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.run_image_button = RoundedButton(bar, text="生成图片", command=self.start_image_generation, width=112, height=42)
        self.run_image_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _scrollable_panel(self, parent: ttk.Frame, width: int) -> tuple[ttk.Frame, ttk.Frame]:
        shell = ttk.Frame(parent, style="Panel.TFrame")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        canvas = tk.Canvas(shell, width=width, bg=PANEL, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        inner = ttk.Frame(canvas, style="Panel.TFrame", padding=22)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.columnconfigure(0, weight=1)

        def update_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, width=canvas.winfo_width())

        inner.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_scroll_region)

        def on_mousewheel(event) -> str:
            delta = -1 * int(event.delta / 120) if event.delta else 0
            if delta:
                canvas.yview_scroll(delta, "units")
            return "break"

        def on_button4(_event) -> str:
            canvas.yview_scroll(-1, "units")
            return "break"

        def on_button5(_event) -> str:
            canvas.yview_scroll(1, "units")
            return "break"

        def bind_wheel(_event) -> None:
            canvas.bind_all("<MouseWheel>", on_mousewheel)
            canvas.bind_all("<Button-4>", on_button4)
            canvas.bind_all("<Button-5>", on_button5)

        def unbind_wheel(_event) -> None:
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", unbind_wheel)
        inner.bind("<Enter>", bind_wheel)
        inner.bind("<Leave>", unbind_wheel)
        return shell, inner

    def _card(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        rows = [int(child.grid_info().get("row", 0)) for child in parent.grid_slaves()]
        row = max(rows, default=-1) + 1
        surface = RoundedPanel(parent, fill=PANEL, radius=24, padding=18)
        surface.grid(row=row, column=0, sticky="ew", pady=(0, 18))
        card = surface.body
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        return card

    def _section_label(self, parent: ttk.Frame, label: str, row: int) -> None:
        ttk.Label(parent, text=label, style="Section.TLabel").grid(row=row, column=0, sticky="w", pady=(14, 4))

    def _hint(self, parent: ttk.Frame, text: str, row: int) -> None:
        ttk.Label(parent, text=text, style="Help.TLabel", wraplength=300).grid(row=row, column=0, sticky="w", pady=(6, 2))

    def _field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, show: str | None = None) -> None:
        ttk.Label(parent, text=label, style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 4))
        RoundedInput(parent, textvariable=variable, show=show or "").grid(row=row + 1, column=0, sticky="ew")

    def _choice_field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, values: tuple[str, ...], row: int) -> None:
        ttk.Label(parent, text=label, style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 4))
        RoundedSelect(parent, textvariable=variable, values=values).grid(row=row + 1, column=0, sticky="ew")

    def _scale_field(self, parent: ttk.Frame, label: str, variable: tk.DoubleVar, row: int) -> None:
        line = tk.Frame(parent, bg=PANEL)
        line.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        line.columnconfigure(0, weight=1)
        ttk.Label(line, text=label, style="PanelMuted.TLabel").grid(row=0, column=0, sticky="w")
        value_label = ttk.Label(line, textvariable=variable, style="PanelMuted.TLabel")
        value_label.grid(row=0, column=1, sticky="e")
        scale = tk.Scale(
            parent,
            from_=0,
            to=100,
            orient="horizontal",
            variable=variable,
            resolution=1,
            showvalue=False,
            bg=PANEL,
            fg=TEXT,
            troughcolor="#dbe7ed",
            activebackground=ACCENT,
            highlightthickness=0,
            bd=0,
        )
        scale.grid(row=row + 1, column=0, sticky="ew")

    def _path_field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, command) -> None:
        ttk.Label(parent, text=label, style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 4))
        line = tk.Frame(parent, bg=PANEL)
        line.grid(row=row + 1, column=0, sticky="ew")
        line.columnconfigure(0, weight=1)
        RoundedInput(line, textvariable=variable).grid(row=0, column=0, sticky="ew")
        RoundedButton(line, text="选择", command=command, width=78, height=38, variant="ghost").grid(row=0, column=1, padx=(8, 0))

    def _path_file_field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, command) -> None:
        self._path_field(parent, label, variable, row, command)

    def _text_area(self, parent: ttk.Frame, row: int, label: str) -> tk.Text:
        ttk.Label(parent, text=label, style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 4))
        text_box = RoundedTextBox(parent, height=110, font=("Microsoft YaHei UI", 10))
        text_box.grid(row=row + 1, column=0, sticky="nsew")
        return text_box.text

    def choose_media_dir(self) -> None:
        path = filedialog.askdirectory(title="选择素材文件夹")
        if path:
            self.media_dir.set(path)

    def choose_music_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 BGM 文件夹")
        if path:
            self.music_dir.set(path)

    def choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择视频输出文件夹")
        if path:
            self.output_dir.set(path)

    def choose_image_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择图片输出文件夹")
        if path:
            self.image_output_dir.set(path)

    def choose_reference_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择参考图片",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")],
        )
        if path:
            self.reference_image.set(path)

    def choose_style_reference_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择风格参考图",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")],
        )
        if path:
            self.style_reference_image.set(path)
            self.reference_image.set(path)

    def choose_content_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择需要改风格的内容图片",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")],
        )
        if path:
            self.content_image.set(path)

    def validate_api(self) -> None:
        self.validate_button.configure(state="disabled")
        self.api_status.configure(text="剪辑 API 验证中", foreground=WARN)

        def worker() -> None:
            try:
                client = OpenAICompatibleClient(
                    LLMConfig(
                        base_url=self.base_url.get(),
                        api_key=self.api_key.get(),
                        model=self.model.get(),
                        timeout_seconds=60,
                    )
                )
                reply = client.validate()
                self.api_validated = True
                self.log_queue.put(f"剪辑 API 验证成功：{reply}")
                self.after(0, lambda: self.api_status.configure(text="剪辑 API 已连接", foreground=OK))
            except Exception as exc:
                self.api_validated = False
                self.log_queue.put(f"剪辑 API 验证失败：{exc}")
                self.after(0, lambda: self.api_status.configure(text="剪辑 API 失败", foreground=BAD))
            finally:
                self.after(0, lambda: self.validate_button.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def start_video_edit(self) -> None:
        if self._busy():
            return
        if not self.api_validated and not messagebox.askyesno("API 未验证", "剪辑 API 还没有验证成功，仍然继续吗？"):
            return
        if not self.media_dir.get().strip():
            messagebox.showwarning("缺少素材", "请选择素材文件夹。")
            return
        if not self.output_dir.get().strip():
            messagebox.showwarning("缺少输出位置", "请选择视频输出文件夹。")
            return

        request = EditRequest(
            media_dir=Path(self.media_dir.get()),
            music_dir=Path(self.music_dir.get()) if self.music_dir.get().strip() else None,
            output_dir=Path(self.output_dir.get()),
            output_name=self.output_name.get().strip() or "ai_auto_cut",
            base_url=self.base_url.get().strip(),
            api_key=self.api_key.get().strip(),
            model=self.model.get().strip(),
            style=self.style_text.get("1.0", "end").strip(),
            keyframe_notes=self.keyframe_text.get("1.0", "end").strip(),
            focus_notes=self.focus_text.get("1.0", "end").strip(),
            target_duration=int(self.target_duration.get()),
            aspect_ratio=self.aspect_ratio.get(),
            prefer_davinci=bool(self.prefer_davinci.get()),
            enable_algorithm=bool(self.enable_algorithm.get()),
        )
        self._set_busy(True)
        self._log("开始自动剪辑视频...")

        def worker() -> None:
            try:
                result = run_edit(request, log=self.log_queue.put)
                self.log_queue.put(f"后端：{result.backend}")
                self.log_queue.put(f"成片：{result.output_video}")
                self.log_queue.put(f"脚本：{result.script_path}")
                self.log_queue.put(f"算法分析：{result.analysis_path}")
                self.after(0, lambda: self._show_dialog("剪辑完成", f"{result.output_video}"))
            except Exception as exc:
                message = str(exc)
                self.log_queue.put(f"剪辑失败：{message}")
                self.after(0, lambda: self._show_dialog("剪辑失败", message, kind="error"))
            finally:
                self.after(0, lambda: self._set_busy(False))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def start_image_generation(self) -> None:
        if self._busy():
            return
        if not self.image_output_dir.get().strip():
            messagebox.showwarning("缺少输出位置", "请选择图片输出文件夹。")
            return
        mode_key = IMAGE_MODES[self.image_mode.get()]
        prompt = self._compose_image_prompt(mode_key)
        if mode_key == "style_reference" and not self.style_reference_image.get().strip():
            messagebox.showwarning("缺少风格参考图", "请先选择一张风格参考图。")
            return
        if mode_key in {"style_reference", "edit_style"} and not self.content_image.get().strip():
            messagebox.showwarning("缺少内容图片", "当前模式需要选择一张内容图片。")
            return

        request = ImageRequest(
            mode=mode_key,
            backend="local_sdxl",
            prompt=prompt,
            output_dir=Path(self.image_output_dir.get()),
            output_name=self.image_output_name.get().strip() or "ai_image",
            api_key=self.image_api_key.get().strip(),
            model=self.image_model.get().strip(),
            reference_image=Path(self.style_reference_image.get()) if self.style_reference_image.get().strip() else None,
            style_reference_image=Path(self.style_reference_image.get()) if self.style_reference_image.get().strip() else None,
            content_image=Path(self.content_image.get()) if self.content_image.get().strip() else None,
            style_description=self.style_analysis_text.get("1.0", "end").strip(),
            size=self.image_size.get(),
            count=int(self.image_count.get()),
            steps=int(self.image_steps.get()),
            seed=int(self.image_seed.get()),
            content_strength=float(self.content_strength.get()) / 100.0,
            style_strength=float(self.style_strength.get()) / 100.0,
            smart_prompt=bool(self.image_smart_prompt.get()),
        )
        self._set_busy(True)
        self._log("开始生成图片...")

        def worker() -> None:
            try:
                result = run_image_generation(request, log=self.log_queue.put)
                for path in result.images:
                    self.log_queue.put(f"图片：{path}")
                self.log_queue.put(f"图片报告：{result.report_path}")
                first = result.images[0] if result.images else ""
                self.after(0, lambda: self._show_dialog("图片生成完成", f"{first}"))
            except Exception as exc:
                message = str(exc)
                self.log_queue.put(f"图片生成失败：{message}")
                self.after(0, lambda: self._show_dialog("图片生成失败", message, kind="error"))
            finally:
                self.after(0, lambda: self._set_busy(False))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def _on_image_mode_changed(self, *_args) -> None:
        if not hasattr(self, "image_mode_hint"):
            return
        mode_key = IMAGE_MODES.get(self.image_mode.get(), "text_to_image")
        hints = {
            "text_to_image": "只写提示词即可；也可以额外选择风格参考图，让 IP-Adapter 注入画风。",
            "style_reference": "需要风格参考图和内容图片：ControlNet 保持内容结构，IP-Adapter 学习参考画风。",
            "edit_style": "只需要内容图片和文字风格描述：ControlNet 保持轮廓，用文字提示改变画风。",
        }
        self.image_mode_hint.configure(text=hints.get(mode_key, ""))

    def start_style_analysis(self) -> None:
        if self._busy():
            return
        if not self.style_reference_image.get().strip():
            messagebox.showwarning("缺少风格参考图", "请先选择一张风格参考图。")
            return
        if not self.image_api_key.get().strip():
            messagebox.showwarning("缺少 DashScope Key", "请先填写 DashScope API Key，或在生成时关闭智能提示词。")
            return

        self._set_busy(True)
        self._log("开始分析风格参考图...")

        def worker() -> None:
            try:
                from .image_llm import LLMService

                service = LLMService(api_key=self.image_api_key.get().strip())
                result = service.analyze_style(Path(self.style_reference_image.get()))
                self.log_queue.put("风格参考图分析完成。")

                def update_text() -> None:
                    self.style_analysis_text.delete("1.0", "end")
                    self.style_analysis_text.insert("1.0", result)

                self.after(0, update_text)
            except Exception as exc:
                message = str(exc)
                self.log_queue.put(f"风格分析失败：{message}")
                self.after(0, lambda: self._show_dialog("风格分析失败", message, kind="error"))
            finally:
                self.after(0, lambda: self._set_busy(False))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def _compose_image_prompt(self, mode_key: str) -> str:
        base = self.image_prompt_text.get("1.0", "end").strip()
        if mode_key == "style_reference":
            return f"用户内容要求：{base}"
        if mode_key == "edit_style":
            return f"用户改风格要求：{base}"
        return base

    def _busy(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.run_video_button.configure(state=state)
        self.run_image_button.configure(state=state)
        if hasattr(self, "analyze_style_button"):
            self.analyze_style_button.configure(state=state)

    def _show_dialog(self, title: str, message: str, kind: str = "info") -> None:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        shell = tk.Frame(dialog, bg=PANEL, padx=26, pady=24)
        shell.grid(row=0, column=0, sticky="nsew")
        accent = BAD if kind == "error" else ACCENT
        tk.Label(
            shell,
            text=title,
            bg=PANEL,
            fg=accent,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            shell,
            text=message,
            bg=PANEL,
            fg=TEXT,
            justify="left",
            wraplength=420,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=1, column=0, sticky="w", pady=(12, 20))
        RoundedButton(shell, text="知道了", command=dialog.destroy, width=112, height=40).grid(row=2, column=0, sticky="e")

        self.update_idletasks()
        width = max(420, dialog.winfo_reqwidth())
        height = dialog.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain_logs(self) -> None:
        try:
            while True:
                self._log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(150, self._drain_logs)


def main() -> None:
    app = VideoAgentApp()
    app.mainloop()


if __name__ == "__main__":
    main()
