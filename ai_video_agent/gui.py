from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .agent import EditRequest, run_edit
from .llm import LLMConfig, OpenAICompatibleClient


BG = "#07111f"
PANEL = "#0c1b2e"
PANEL_2 = "#10243a"
FIELD = "#0a1626"
TEXT = "#e7f1ff"
MUTED = "#8aa4bf"
ACCENT = "#23d5ff"
ACCENT_2 = "#7c5cff"
OK = "#43e58f"
WARN = "#ffd166"
BAD = "#ff5c7a"


class VideoAgentApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AI Video Agent")
        self.geometry("1120x720")
        self.minsize(980, 620)
        self.configure(bg=BG)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.base_url = tk.StringVar(value="https://api.deepseek.com/v1")
        self.api_key = tk.StringVar()
        self.model = tk.StringVar(value="deepseek-chat")
        self.media_dir = tk.StringVar()
        self.music_dir = tk.StringVar()
        self.output_dir = tk.StringVar(value=str((Path.cwd() / "outputs" / "rough_cuts").resolve()))
        self.output_name = tk.StringVar(value="ai_auto_cut")
        self.aspect_ratio = tk.StringVar(value="竖屏 9:16")
        self.target_duration = tk.IntVar(value=30)
        self.prefer_davinci = tk.BooleanVar(value=True)
        self.api_validated = False

        self._setup_style()
        self._build_ui()
        self.after(150, self._drain_logs)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, font=("Microsoft YaHei UI", 10))
        style.configure("Root.TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel2.TFrame", background=PANEL_2)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 22, "bold"))
        style.configure("Accent.TLabel", background=BG, foreground=ACCENT, font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("CardTitle.TLabel", background=PANEL, foreground=TEXT, font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Status.TLabel", background=PANEL_2, foreground=WARN, font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, bordercolor="#1e3a5c")
        style.map("TEntry", fieldbackground=[("focus", "#0e2138")], bordercolor=[("focus", ACCENT)])
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, arrowcolor=ACCENT)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], selectbackground=[("readonly", FIELD)])
        style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT, bordercolor="#1e3a5c")
        style.configure("Primary.TButton", background=ACCENT, foreground="#00111f", borderwidth=0, padding=(16, 10), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", "#67e5ff"), ("disabled", "#2a5666")])
        style.configure("Ghost.TButton", background="#162b45", foreground=TEXT, borderwidth=0, padding=(12, 8))
        style.map("Ghost.TButton", background=[("active", "#1f3f63"), ("disabled", "#182536")])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", TEXT)])

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, style="Root.TFrame", padding=18)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.rowconfigure(2, weight=0)

        self._build_header(root)

        body = ttk.Frame(root, style="Root.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left_shell = ttk.Frame(body, style="Panel.TFrame")
        left_shell.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        left_shell.columnconfigure(0, weight=1)
        left_shell.rowconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_shell, width=330, bg=PANEL, highlightthickness=0, bd=0)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scrollbar = ttk.Scrollbar(left_shell, orient="vertical", command=left_canvas.yview)
        left_scrollbar.grid(row=0, column=1, sticky="ns")
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left = ttk.Frame(left_canvas, style="Panel.TFrame", padding=16)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.columnconfigure(0, weight=1)

        def update_scroll_region(_event=None) -> None:
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
            left_canvas.itemconfigure(left_window, width=left_canvas.winfo_width())

        left.bind("<Configure>", update_scroll_region)
        left_canvas.bind("<Configure>", update_scroll_region)

        right = ttk.Frame(body, style="Root.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_model_card(left)
        self._build_run_card(left)
        self._build_prompt_card(right)
        self._build_log_card(right)
        self._build_action_bar(root)

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="Root.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="AI Video Agent", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="本地自动剪辑 · DaVinci 优先 · FFmpeg 后备 · OpenAI-compatible", style="Accent.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        self.api_status = ttk.Label(header, text="API 未验证", style="Status.TLabel", padding=(12, 8))
        self.api_status.grid(row=0, column=1, rowspan=2, sticky="e")

    def _build_model_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame")
        card.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="模型连接", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))

        self._field(card, "Base URL", self.base_url, 1)
        self._field(card, "API Key", self.api_key, 3, show="*")
        self._field(card, "模型", self.model, 5)

        self.validate_button = ttk.Button(card, text="验证 API", style="Primary.TButton", command=self.validate_api)
        self.validate_button.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(card, text="DeepSeek 示例：api.deepseek.com/v1 + deepseek-chat", style="PanelMuted.TLabel", wraplength=290).grid(
            row=8, column=0, sticky="w", pady=(10, 0)
        )

    def _build_run_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame")
        card.grid(row=1, column=0, sticky="new")
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="任务设置", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))

        self._path_field(card, "素材文件夹", self.media_dir, 1, self.choose_media_dir)
        self._path_field(card, "BGM 文件夹", self.music_dir, 3, self.choose_music_dir)
        self._path_field(card, "输出文件夹", self.output_dir, 5, self.choose_output_dir)
        self._field(card, "输出名称", self.output_name, 7)

        row = 9
        ttk.Label(card, text="画幅", style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w", pady=(10, 4))
        ttk.Combobox(
            card,
            textvariable=self.aspect_ratio,
            values=("竖屏 9:16", "横屏 16:9", "方形 1:1"),
            state="readonly",
        ).grid(row=row + 1, column=0, sticky="ew")

        ttk.Label(card, text="目标时长（秒）", style="PanelMuted.TLabel").grid(row=row + 2, column=0, sticky="w", pady=(10, 4))
        ttk.Spinbox(card, from_=5, to=600, textvariable=self.target_duration).grid(row=row + 3, column=0, sticky="ew")

        ttk.Checkbutton(card, text="优先 DaVinci，失败后 FFmpeg", variable=self.prefer_davinci).grid(row=row + 4, column=0, sticky="w", pady=(12, 0))

        ttk.Label(card, text="检查无误后点击底部按钮开始。", style="PanelMuted.TLabel", wraplength=280).grid(
            row=row + 5, column=0, sticky="w", pady=(18, 0)
        )

    def _build_prompt_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=16)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text="剪辑指令", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, text="输入你想要的风格、关键帧偏好和重点内容，Agent 会直接剪完。", style="PanelMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 12)
        )

        self.style_text = self._text_area(card, 2, "视频风格")
        self.style_text.insert("1.0", "干净、有节奏、有轻微高级感；开头 3 秒抓人，中段突出重点，结尾收束。")

        self.keyframe_text = self._text_area(card, 4, "关键帧补充")
        self.keyframe_text.insert("1.0", "优先选择主体清楚、光线好、动作明确的镜头；避开明显抖动和无意义空镜。")

        self.focus_text = self._text_area(card, 6, "重点剪辑补充")
        self.focus_text.insert("1.0", "重点内容多停留一点，普通过渡镜头快切；需要字幕总结每个段落。")

    def _build_log_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=16)
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        ttk.Label(card, text="运行日志", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.log_text = tk.Text(
            card,
            height=12,
            wrap="word",
            state="disabled",
            bg="#06101c",
            fg="#bfe7ff",
            insertbackground=TEXT,
            relief="flat",
            padx=12,
            pady=10,
            font=("Consolas", 10),
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(card, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, style="Panel2.TFrame", padding=(14, 12))
        bar.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        bar.columnconfigure(0, weight=1)
        ttk.Label(
            bar,
            text="输出会写入你选择的文件夹，同时保留脚本、字幕和 timeline.json。",
            style="Status.TLabel",
            foreground=MUTED,
        ).grid(row=0, column=0, sticky="w")
        self.run_button = ttk.Button(bar, text="开始自动剪辑", style="Primary.TButton", command=self.start_edit)
        self.run_button.grid(row=0, column=1, sticky="e")

    def _field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, show: str | None = None) -> None:
        ttk.Label(parent, text=label, style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 4))
        ttk.Entry(parent, textvariable=variable, show=show or "").grid(row=row + 1, column=0, sticky="ew")

    def _path_field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int, command) -> None:
        ttk.Label(parent, text=label, style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 4))
        line = ttk.Frame(parent, style="Panel.TFrame")
        line.grid(row=row + 1, column=0, sticky="ew")
        line.columnconfigure(0, weight=1)
        ttk.Entry(line, textvariable=variable).grid(row=0, column=0, sticky="ew")
        ttk.Button(line, text="选择", style="Ghost.TButton", command=command).grid(row=0, column=1, padx=(8, 0))

    def _text_area(self, parent: ttk.Frame, row: int, label: str) -> tk.Text:
        ttk.Label(parent, text=label, style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 4))
        text = tk.Text(
            parent,
            height=4,
            wrap="word",
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            padx=10,
            pady=8,
            font=("Microsoft YaHei UI", 10),
        )
        text.grid(row=row + 1, column=0, sticky="ew")
        return text

    def choose_media_dir(self) -> None:
        path = filedialog.askdirectory(title="选择素材文件夹")
        if path:
            self.media_dir.set(path)

    def choose_music_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 BGM 文件夹")
        if path:
            self.music_dir.set(path)

    def choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出文件夹")
        if path:
            self.output_dir.set(path)

    def validate_api(self) -> None:
        self.validate_button.configure(state="disabled")
        self.api_status.configure(text="API 验证中", foreground=WARN)

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
                self.log_queue.put(f"API 验证成功：{reply}")
                self.after(0, lambda: self.api_status.configure(text="API 已连接", foreground=OK))
            except Exception as exc:
                self.api_validated = False
                self.log_queue.put(f"API 验证失败：{exc}")
                self.after(0, lambda: self.api_status.configure(text="API 失败", foreground=BAD))
            finally:
                self.after(0, lambda: self.validate_button.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def start_edit(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.api_validated and not messagebox.askyesno("API 未验证", "API 还没有验证成功，仍然继续吗？"):
            return
        if not self.media_dir.get().strip():
            messagebox.showwarning("缺少素材", "请选择素材文件夹。")
            return
        if not self.output_dir.get().strip():
            messagebox.showwarning("缺少输出位置", "请选择输出文件夹。")
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
        )
        self.run_button.configure(state="disabled")
        self._log("开始自动剪辑...")

        def worker() -> None:
            try:
                result = run_edit(request, log=self.log_queue.put)
                self.log_queue.put(f"后端：{result.backend}")
                self.log_queue.put(f"成片：{result.output_video}")
                self.log_queue.put(f"脚本：{result.script_path}")
                self.after(0, lambda: messagebox.showinfo("完成", f"剪辑完成：\n{result.output_video}"))
            except Exception as exc:
                self.log_queue.put(f"剪辑失败：{exc}")
                self.after(0, lambda: messagebox.showerror("剪辑失败", str(exc)))
            finally:
                self.after(0, lambda: self.run_button.configure(state="normal"))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

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
