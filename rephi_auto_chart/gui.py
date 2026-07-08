from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .analysis import AudioAnalysis, analyze_audio
from .batch import batch_generate
from .chart_analyzer import analyze_chart_file
from .config import AssistantConfig, Difficulty
from .diagnostics import run_startup_checks
from .exporter import export_pez, export_rephi_package, export_rpe_chart
from .generator import generate_chart
from .runtime import (
    audio_default_export_path,
    configured_export_path,
    configured_theme_mode,
    effective_theme,
    default_export_path,
    ensure_runtime_layout,
    save_configured_export_path,
    save_configured_theme_mode,
)


AUDIO_FILE_PATTERN = "*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.alac"
CHART_CANVAS_WIDTH = 980

THEME_PALETTES = {
    "light": {
        "bg": "#f5f5f5",
        "panel": "#ffffff",
        "text": "#202124",
        "muted": "#5f6368",
        "entry_bg": "#ffffff",
        "entry_fg": "#202124",
        "chart_bg": "#111111",
        "chart_border": "#444444",
        "chart_text": "#eeeeee",
        "log_bg": "#ffffff",
        "log_fg": "#202124",
        "select_bg": "#d7e8ff",
        "error": "#b3261e",
        "warning": "#8a5a00",
        "success": "#137333",
        "info": "#202124",
    },
    "dark": {
        "bg": "#121212",
        "panel": "#1b1b1b",
        "text": "#f0f0f0",
        "muted": "#b8b8b8",
        "entry_bg": "#242424",
        "entry_fg": "#f0f0f0",
        "chart_bg": "#1e1e1e",
        "chart_border": "#333333",
        "chart_text": "#f0f0f0",
        "log_bg": "#181818",
        "log_fg": "#f0f0f0",
        "select_bg": "#264f78",
        "error": "#ff6b6b",
        "warning": "#ffd166",
        "success": "#7bd88f",
        "info": "#f0f0f0",
    },
}


def summarize_sections(sections: list[tuple[float, float, str]]) -> str:
    counts: dict[str, int] = {}
    order: list[str] = []
    for _, _, label in sections:
        if label not in counts:
            counts[label] = 0
            order.append(label)
        counts[label] += 1
    return ", ".join(f"{label} x{counts[label]}" for label in order) if order else "None"


def format_full_sections(sections: list[tuple[float, float, str]]) -> str:
    return ", ".join(label for _, _, label in sections) or "None"


def format_song_info(analysis: AudioAnalysis) -> str:
    return (
        f"Length: {analysis.duration:.2f}s | BPM: {analysis.bpm:.2f} | Sample Rate: {analysis.sample_rate} Hz\n"
        f"Sections: {summarize_sections(analysis.sections)}"
    )


class AutoChartGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Re:PhiEdit Auto Chart Assistant 2.5.2")
        self.geometry("1180x820")
        self.minsize(1000, 700)
        self.runtime_layout, self.runtime_messages = ensure_runtime_layout()
        self.style = ttk.Style(self)
        self.audio_path = tk.StringVar()
        self.output_mode = tk.StringVar(value="pez")
        initial_output = configured_export_path("pez", self.runtime_layout)
        self.output_path = tk.StringVar(value=str(initial_output))
        save_configured_export_path(self.output_path.get(), self.runtime_layout)
        self.difficulty = tk.StringVar(value=Difficulty.HD.value)
        self.density = tk.DoubleVar(value=1.0)
        self.enable_hold = tk.BooleanVar(value=True)
        self.enable_drag = tk.BooleanVar(value=True)
        self.enable_flick = tk.BooleanVar(value=True)
        self.auto_timing = tk.BooleanVar(value=True)
        self.manual_offset_ms = tk.IntVar(value=0)
        self.snap_strength = tk.DoubleVar(value=0.65)
        self.bpm_aware_density = tk.BooleanVar(value=True)
        self.chart_style = tk.StringVar(value="Official-like")
        self.theme_mode = tk.StringVar(value=configured_theme_mode(self.runtime_layout))
        self.theme = tk.StringVar(value=effective_theme(self.theme_mode.get(), self.runtime_layout))
        self.status = tk.StringVar(value="Ready")
        self.song_info = tk.StringVar(value="No audio loaded")
        self.sections_summary = tk.StringVar(value="Sections: None")
        self.stats_info = tk.StringVar(value="No chart generated")
        self.phrase_info = tk.StringVar(value="No phrase data")
        self.batch_files: list[Path] = []
        self.last_output: Path | None = None
        self.last_analysis: AudioAnalysis | None = None
        self.current_sections: list[tuple[float, float, str]] = []
        self.show_full_sections = False
        self.export_path_user_modified = False
        self.messages: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self.chart_canvases: list[tk.Canvas] = []
        self.text_widgets: list[tk.Text] = []
        self._build()
        self._apply_theme(save=False)
        self._run_startup_checks()
        self.after(100, self._drain_messages)

    def _build(self) -> None:
        self._build_menu()
        self.root_frame = ttk.Frame(self, padding=10)
        self.root_frame.pack(fill=tk.BOTH, expand=True)

        self.top_controls = ttk.Frame(self.root_frame)
        self.top_controls.pack(fill=tk.X)
        top = self.top_controls
        ttk.Button(top, text="Select Audio", command=self._select_audio).grid(row=0, column=0, sticky="ew")
        ttk.Entry(top, textvariable=self.audio_path).grid(row=0, column=1, columnspan=5, sticky="ew", padx=8)
        ttk.Button(top, text="Batch Select", command=self._select_batch).grid(row=0, column=6, sticky="ew")
        ttk.Label(top, text="Difficulty").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Combobox(top, textvariable=self.difficulty, values=[d.value for d in Difficulty], state="readonly", width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(top, text="Density").grid(row=1, column=2, sticky="e")
        ttk.Scale(top, variable=self.density, from_=0.2, to=1.8).grid(row=1, column=3, sticky="ew")
        ttk.Checkbutton(top, text="Hold", variable=self.enable_hold).grid(row=1, column=4, sticky="w")
        ttk.Checkbutton(top, text="Drag", variable=self.enable_drag).grid(row=1, column=5, sticky="w")
        ttk.Checkbutton(top, text="Flick", variable=self.enable_flick).grid(row=1, column=6, sticky="w")
        ttk.Checkbutton(top, text="Auto Timing Calibration", variable=self.auto_timing).grid(row=2, column=0, sticky="w")
        ttk.Label(top, text="Manual Offset ms").grid(row=2, column=1, sticky="e")
        ttk.Spinbox(top, textvariable=self.manual_offset_ms, from_=-300, to=300, increment=5, width=8).grid(row=2, column=2, sticky="w")
        ttk.Label(top, text="Snap Strength").grid(row=2, column=3, sticky="e")
        ttk.Scale(top, variable=self.snap_strength, from_=0.0, to=1.0).grid(row=2, column=4, columnspan=2, sticky="ew")
        ttk.Checkbutton(top, text="BPM-aware Density", variable=self.bpm_aware_density).grid(row=3, column=0, sticky="w")
        ttk.Label(top, text="Chart Style").grid(row=3, column=1, sticky="e")
        ttk.Combobox(top, textvariable=self.chart_style, values=["Official-like", "Balanced", "Dense", "Experimental"], state="readonly", width=16).grid(row=3, column=2, sticky="w")
        for index, (label, value) in enumerate((("PEZ Import Package", "pez"), ("Folder Package", "folder"), ("chart.json", "json"))):
            ttk.Radiobutton(top, text=label, value=value, variable=self.output_mode, command=self._sync_output_default).grid(row=4, column=index + 1, sticky="w")
        ttk.Button(top, text="Export To", command=self._select_output).grid(row=5, column=0, sticky="ew")
        ttk.Entry(top, textvariable=self.output_path).grid(row=5, column=1, columnspan=5, sticky="ew", padx=8)
        ttk.Button(top, text="Generate", command=self._generate).grid(row=5, column=6, sticky="ew")
        ttk.Button(top, text="Open Output Folder", command=self._open_output_folder).grid(row=6, column=6, sticky="ew", pady=4)
        top.columnconfigure(3, weight=1)

        self.progress = ttk.Progressbar(self.root_frame, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=6)
        ttk.Label(self.root_frame, textvariable=self.status).pack(anchor="w")

        self.workspace_frame = ttk.Frame(self.root_frame)
        self.workspace_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 6))
        self.workspace_canvas = tk.Canvas(self.workspace_frame, highlightthickness=0, yscrollincrement=18)
        self.workspace_scrollbar = ttk.Scrollbar(self.workspace_frame, orient=tk.VERTICAL, command=self.workspace_canvas.yview)
        self.workspace_canvas.configure(yscrollcommand=self.workspace_scrollbar.set)
        self.workspace_canvas.grid(row=0, column=0, sticky="nsew")
        self.workspace_scrollbar.grid(row=0, column=1, sticky="ns")
        self.workspace_frame.rowconfigure(0, weight=1)
        self.workspace_frame.columnconfigure(0, weight=1)
        self.workspace_content = ttk.Frame(self.workspace_canvas)
        self.workspace_window = self.workspace_canvas.create_window((0, 0), window=self.workspace_content, anchor="nw")
        self.workspace_content.bind("<Configure>", self._update_workspace_scrollregion)
        self.workspace_canvas.bind("<Configure>", self._resize_workspace_window)
        self._bind_mousewheel(self.workspace_canvas, self._on_workspace_mousewheel)

        self._build_workspace(self.workspace_content)

        self.output_notebook = ttk.Notebook(self.root_frame)
        self.output_notebook.pack(fill=tk.BOTH, expand=False)
        self.stats_tab = ttk.Frame(self.output_notebook)
        self.log_tab = ttk.Frame(self.output_notebook)
        self.output_notebook.add(self.stats_tab, text="Stats")
        self.output_notebook.add(self.log_tab, text="Log")
        self.stats_text = ScrolledText(self.stats_tab, height=9, wrap=tk.NONE, font=("Consolas", 10))
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        self.text_widgets.append(self.stats_text)
        self._bind_mousewheel(self.stats_text, self._on_text_mousewheel)
        self._set_stats_text(self.stats_info.get())
        self.log = ScrolledText(self.log_tab, height=9, wrap=tk.NONE, font=("Consolas", 10))
        self.log.pack(fill=tk.BOTH, expand=True)
        self.text_widgets.append(self.log)
        self._bind_mousewheel(self.log, self._on_text_mousewheel)
        self._configure_log_tags()

    def _build_workspace(self, parent: ttk.Frame) -> None:
        self.info_card = ttk.LabelFrame(parent, text="Song Info")
        self.info_card.pack(fill=tk.X, pady=(0, 8))
        self.song_summary_label = ttk.Label(self.info_card, textvariable=self.song_info, anchor="w")
        self.song_summary_label.pack(fill=tk.X, padx=8, pady=(6, 2))
        self.sections_summary_label = ttk.Label(self.info_card, textvariable=self.sections_summary, anchor="w")
        self.sections_summary_label.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.sections_toggle_button = ttk.Button(self.info_card, text="Show Full Sections", command=self._toggle_full_sections)
        self.sections_toggle_button.pack(anchor="w", padx=8, pady=(0, 6))
        self.full_sections_text = ScrolledText(self.info_card, height=4, wrap=tk.WORD, font=("Consolas", 9))
        self.text_widgets.append(self.full_sections_text)
        self._bind_mousewheel(self.full_sections_text, self._on_text_mousewheel)
        self.full_sections_text.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.full_sections_text.pack_forget()

        self.wave_canvas = self._create_chart_card(parent, "Waveform", 150)
        self.density_canvas = self._create_chart_card(parent, "Density per 10s", 130)
        self.pattern_canvas = self._create_chart_card(parent, "Pattern Density", 120)
        self.layout_canvas = self._create_chart_card(parent, "Layout Heatmap", 120)

    def _create_chart_card(self, parent: ttk.Frame, title: str, height: int) -> tk.Canvas:
        card = ttk.LabelFrame(parent, text=title)
        card.pack(fill=tk.X, pady=8)
        canvas = tk.Canvas(card, width=CHART_CANVAS_WIDTH, height=height, xscrollincrement=16, highlightthickness=1)
        scrollbar = ttk.Scrollbar(card, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(xscrollcommand=scrollbar.set, scrollregion=(0, 0, CHART_CANVAS_WIDTH, height))
        canvas.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        scrollbar.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        card.columnconfigure(0, weight=1)
        self.chart_canvases.append(canvas)
        self._bind_mousewheel(canvas, self._on_workspace_mousewheel)
        return canvas

    def _update_workspace_scrollregion(self, _event: tk.Event | None = None) -> None:
        self.workspace_canvas.configure(scrollregion=self.workspace_canvas.bbox("all"))

    def _resize_workspace_window(self, event: tk.Event) -> None:
        self.workspace_canvas.itemconfigure(self.workspace_window, width=event.width)
        self._update_workspace_scrollregion()

    def _build_menu(self) -> None:
        self.menu_bar = tk.Menu(self)
        self.view_menu = tk.Menu(self.menu_bar, tearoff=False)
        self.theme_menu = tk.Menu(self.view_menu, tearoff=False)
        for label, value in (("System", "system"), ("Light", "light"), ("Dark", "dark")):
            self.theme_menu.add_radiobutton(label=label, variable=self.theme_mode, value=value, command=self._on_theme_mode_changed)
        self.view_menu.add_cascade(label="Theme", menu=self.theme_menu)
        self.menu_bar.add_cascade(label="View", menu=self.view_menu)
        self.config(menu=self.menu_bar)

    def _bind_mousewheel(self, widget: tk.Widget, handler) -> None:
        widget.bind("<MouseWheel>", handler)
        widget.bind("<Button-4>", handler)
        widget.bind("<Button-5>", handler)

    def _mousewheel_units(self, event: tk.Event) -> int:
        event_num = getattr(event, "num", None)
        if event_num == 4:
            return -3
        if event_num == 5:
            return 3
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return 0
        return -1 * max(1, abs(int(delta / 120))) * (1 if delta > 0 else -1)

    def _on_workspace_mousewheel(self, event: tk.Event) -> str:
        units = self._mousewheel_units(event)
        if units:
            self.workspace_canvas.yview_scroll(units, "units")
        return "break"

    def _on_text_mousewheel(self, event: tk.Event) -> str:
        units = self._mousewheel_units(event)
        if units:
            event.widget.yview_scroll(units, "units")
        return "break"

    def _chart_width(self, canvas: tk.Canvas) -> int:
        height = int(canvas["height"])
        canvas.configure(scrollregion=(0, 0, CHART_CANVAS_WIDTH, height))
        return CHART_CANVAS_WIDTH

    def _run_startup_checks(self) -> None:
        result = run_startup_checks(Path(self.output_path.get()).parent)
        for message in result.messages:
            self._log(message)
        if not result.ok:
            messagebox.showwarning("Startup Check", "\n".join(result.messages))

    def _select_audio(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Audio", AUDIO_FILE_PATTERN), ("All", "*.*")])
        if path:
            audio = Path(path)
            self.audio_path.set(path)
            self._apply_audio_export_default(audio)
            self._analyze_for_display(audio)

    def _select_batch(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("Audio", AUDIO_FILE_PATTERN), ("All", "*.*")])
        self.batch_files = [Path(path) for path in paths]
        if self.batch_files:
            self.audio_path.set(f"{len(self.batch_files)} files selected")
            self.status.set("Batch mode ready")

    def _select_output(self) -> None:
        mode = self.output_mode.get()
        current = Path(self.output_path.get())
        initial_dir = current if current.is_dir() else current.parent
        if mode == "json":
            path = filedialog.asksaveasfilename(initialdir=str(initial_dir), defaultextension=".json", filetypes=[("RPE JSON", "*.json")])
        elif mode == "pez":
            path = filedialog.asksaveasfilename(initialdir=str(initial_dir), defaultextension=".pez", filetypes=[("Re:PhiEdit PEZ", "*.pez")])
        else:
            path = filedialog.askdirectory(initialdir=str(initial_dir))
        if path:
            self.export_path_user_modified = True
            self.output_path.set(path)
            save_configured_export_path(path, self.runtime_layout)

    def _apply_audio_export_default(self, audio: Path) -> None:
        if self.export_path_user_modified:
            should_update = messagebox.askyesno("Update Export Path", "Use the selected audio filename for the export path?")
            if not should_update:
                return
        path = audio_default_export_path(audio, self.output_mode.get(), self.runtime_layout.export_root)
        self.export_path_user_modified = False
        self.output_path.set(str(path))
        save_configured_export_path(path, self.runtime_layout)

    def _sync_output_default(self) -> None:
        if self.export_path_user_modified:
            save_configured_export_path(self.output_path.get(), self.runtime_layout)
            return
        mode = self.output_mode.get()
        current_audio = Path(self.audio_path.get()) if self.audio_path.get() else None
        if current_audio and current_audio.exists():
            path = audio_default_export_path(current_audio, mode, self.runtime_layout.export_root)
        else:
            path = default_export_path(mode)
        self.output_path.set(str(path))
        save_configured_export_path(path, self.runtime_layout)

    def _set_song_info(self, text: str) -> None:
        self.song_info.set(text)

    def _set_sections(self, sections: list[tuple[float, float, str]]) -> None:
        self.current_sections = sections
        self.sections_summary.set(f"Sections: {summarize_sections(sections)}")
        self._set_full_sections_text(format_full_sections(sections))

    def _set_full_sections_text(self, text: str) -> None:
        if hasattr(self, "full_sections_text"):
            self.full_sections_text.configure(state=tk.NORMAL)
            self.full_sections_text.delete("1.0", tk.END)
            self.full_sections_text.insert(tk.END, text)
            self.full_sections_text.configure(state=tk.DISABLED)

    def _toggle_full_sections(self) -> None:
        self.show_full_sections = not self.show_full_sections
        if self.show_full_sections:
            self.sections_toggle_button.configure(text="Hide Full Sections")
            self.full_sections_text.pack(fill=tk.X, padx=8, pady=(0, 8))
        else:
            self.sections_toggle_button.configure(text="Show Full Sections")
            self.full_sections_text.pack_forget()
        self._update_workspace_scrollregion()

    def _set_stats_text(self, text: str) -> None:
        self.stats_info.set(text)
        if hasattr(self, "stats_text"):
            combined = text
            if self.phrase_info.get() and self.phrase_info.get() != "No phrase data":
                combined = f"{combined}\n\nPhrase / Quality\n{self.phrase_info.get()}"
            self.stats_text.configure(state=tk.NORMAL)
            self.stats_text.delete("1.0", tk.END)
            self.stats_text.insert(tk.END, combined)
            self.stats_text.configure(state=tk.DISABLED)

    def _set_phrase_text(self, text: str) -> None:
        self.phrase_info.set(text)
        self._set_stats_text(self.stats_info.get())

    def _analyze_for_display(self, audio: Path) -> None:
        self.progress.start()
        self.status.set("Analyzing audio...")
        threading.Thread(target=self._analysis_worker, args=(audio,), daemon=True).start()

    def _analysis_worker(self, audio: Path) -> None:
        try:
            analysis = analyze_audio(audio)
            self.messages.put(("analysis", analysis))
        except Exception as exc:
            self.messages.put(("error", self._friendly_error(exc)))
        finally:
            self.messages.put(("stop", None))

    def _generate(self) -> None:
        if self.batch_files:
            self.progress.start()
            threading.Thread(target=self._batch_worker, daemon=True).start()
            return
        audio = Path(self.audio_path.get())
        if not audio.exists():
            messagebox.showwarning("Missing Audio", "Please select a valid audio file first.")
            return
        self.progress.start()
        self.status.set("Generating chart...")
        threading.Thread(target=self._worker, args=(audio,), daemon=True).start()

    def _config(self) -> AssistantConfig:
        return AssistantConfig(
            difficulty=Difficulty(self.difficulty.get()),
            overall_density=self.density.get(),
            enable_hold=self.enable_hold.get(),
            enable_drag=self.enable_drag.get(),
            enable_flick=self.enable_flick.get(),
            auto_timing_calibration=self.auto_timing.get(),
            manual_offset_ms=self.manual_offset_ms.get(),
            snap_strength=self.snap_strength.get(),
            bpm_aware_density=self.bpm_aware_density.get(),
            chart_style=self.chart_style.get(),
            export_path=self.output_path.get(),
        )

    def _worker(self, audio: Path) -> None:
        try:
            analysis = self.last_analysis if self.last_analysis and self.last_analysis.path == audio else analyze_audio(audio)
            chart = generate_chart(analysis, self._config(), audio.name)
            mode = self.output_mode.get()
            if mode == "pez":
                output = export_pez(chart, self.output_path.get(), audio)
            elif mode == "folder":
                output = export_rephi_package(chart, self.output_path.get(), audio)
            else:
                output = export_rpe_chart(chart, self.output_path.get())
            save_configured_export_path(self.output_path.get(), self.runtime_layout)
            self.messages.put(("generated", (analysis, chart, Path(output))))
        except Exception as exc:
            self.messages.put(("error", self._friendly_error(exc)))
        finally:
            self.messages.put(("stop", None))

    def _batch_worker(self) -> None:
        try:
            output_target = Path(self.output_path.get())
            output_dir = output_target.parent if output_target.suffix else output_target
            outputs = batch_generate(self.batch_files, output_dir, self._config(), export_format="pez")
            save_configured_export_path(output_dir, self.runtime_layout)
            self.messages.put(("batch", outputs))
        except Exception as exc:
            self.messages.put(("error", self._friendly_error(exc)))
        finally:
            self.messages.put(("stop", None))

    def _drain_messages(self) -> None:
        while not self.messages.empty():
            kind, payload = self.messages.get()
            if kind == "stop":
                self.progress.stop()
            elif kind == "error":
                self.status.set("Error")
                self._log(str(payload))
                messagebox.showerror("Auto Chart Assistant", str(payload))
            elif kind == "analysis":
                self.last_analysis = payload  # type: ignore[assignment]
                self._show_analysis(payload)  # type: ignore[arg-type]
            elif kind == "generated":
                analysis, chart, output = payload  # type: ignore[misc]
                self.last_output = output
                self._show_generated(analysis, chart, output)
            elif kind == "batch":
                outputs = payload  # type: ignore[assignment]
                self.last_output = Path(outputs[0]).parent if outputs else None
                self.status.set(f"Batch finished: {len(outputs)} PEZ files")
                self._log(f"Batch finished: {outputs}")
                self._finish_dialog()
        self.after(100, self._drain_messages)

    def _show_analysis(self, analysis: AudioAnalysis) -> None:
        self.status.set("Audio analyzed")
        self._set_song_info(format_song_info(analysis))
        self._set_sections(analysis.sections)
        self._draw_waveform(analysis)

    def _show_generated(self, analysis: AudioAnalysis, chart: dict, output: Path) -> None:
        report_path = output if output.suffix.lower() in {".pez", ".json"} else output / "chart.json"
        report = analyze_chart_file(report_path)
        self.status.set(f"Generation finished: {output}")
        self._set_stats_text(
            f"Tap: {report.tap_count}\nHold: {report.hold_count}\nDrag: {report.drag_count}\nFlick: {report.flick_count}\n"
            f"Total Note: {report.total_notes}\nLongest Hold: {report.longest_hold_seconds:.2f}s\n"
            f"Average Density: {report.average_density:.2f}/10s\nMax Density: {report.max_density}/10s\nNPS: {report.nps:.2f}"
        )
        auto_report = chart.get("META", {}).get("autoChartReport", {})
        if auto_report:
            ratios = auto_report.get("type_ratios", {})
            target = auto_report.get("density_target", {})
            self._set_stats_text(
                self.stats_info.get()
                + f"\nRecommended Offset: {auto_report.get('recommended_offset_ms', 0)} ms"
                + f"\nFinal Offset: {auto_report.get('final_offset_ms', 0)} ms"
                + f"\nTarget Notes: {target.get('target_notes_final', 0)}"
                + f"\nActual Notes: {auto_report.get('note_count', 0)}"
                + f"\nTap Ratio: {ratios.get('tap', 0):.2f}"
                + f"\nDrag Ratio: {ratios.get('drag', 0):.2f}"
                + f"\nFlick Ratio: {ratios.get('flick', 0):.2f}"
                + f"\nHold Ratio: {ratios.get('hold', 0):.2f}"
            )
            phrase = auto_report.get("phrase_summary", {})
            quality = auto_report.get("quality_score", {})
            self._set_phrase_text(
                f"Quality Score: {quality.get('Overall', 0)}\n"
                f"Phrase Count: {phrase.get('phrase_count', 0)}\n"
                f"Drag Chain Count: {phrase.get('drag_chain_count', 0)}\n"
                f"Longest Drag Chain: {phrase.get('longest_drag_chain', 0)}\n"
                f"Pattern Diversity: {auto_report.get('pattern_diversity_score', quality.get('Pattern Diversity', 0))}\n"
                f"Layout Diversity: {auto_report.get('layout_diversity_score', 0)}\n"
                f"Playability: {auto_report.get('playability_score', 0)}\n"
                f"Avg Jump: {auto_report.get('average_jump_distance', 0)}\n"
                f"Hand Alternation: {auto_report.get('hand_alternation_score', 0)}\n"
                f"Longest Same Pattern: {auto_report.get('longest_same_pattern', 0)}\n"
                f"Longest Same Lane: {auto_report.get('longest_same_lane', 0)}"
            )
        self._draw_waveform(analysis)
        self._draw_density(report.per_10s)
        self._draw_pattern_density(chart)
        self._draw_layout_heatmap(chart)
        self._log(f"Generation finished: {output}")
        if auto_report:
            self._log(
                "Quality report: "
                f"BPM={auto_report.get('bpm')}, notes={auto_report.get('note_count')}, "
                f"target={auto_report.get('density_target', {}).get('target_notes_final')}, "
                f"NPS={auto_report.get('average_nps')}, max10s={auto_report.get('max_10s_nps')}, "
                f"offset={auto_report.get('final_offset_ms')}ms"
                f", quality={auto_report.get('quality_score', {}).get('Overall')}"
            )
        self._finish_dialog()

    def _palette(self) -> dict[str, str]:
        return THEME_PALETTES.get(self.theme.get(), THEME_PALETTES["light"])

    def _apply_theme(self, save: bool = True) -> None:
        self.theme.set(effective_theme(self.theme_mode.get(), self.runtime_layout))
        palette = self._palette()
        if save:
            save_configured_theme_mode(self.theme_mode.get(), self.runtime_layout)
        self.configure(bg=palette["bg"])
        self.style.theme_use("default")
        self.style.configure("TFrame", background=palette["bg"])
        self.style.configure("TLabelframe", background=palette["bg"], foreground=palette["text"], bordercolor=palette["chart_border"])
        self.style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TLabel", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TButton", background=palette["panel"], foreground=palette["text"])
        self.style.configure("TCheckbutton", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TRadiobutton", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TNotebook", background=palette["bg"], borderwidth=0)
        self.style.configure("TNotebook.Tab", background=palette["panel"], foreground=palette["text"], padding=(12, 5))
        self.style.map("TNotebook.Tab", background=[("selected", palette["entry_bg"])], foreground=[("selected", palette["text"])])
        self.style.configure("TEntry", fieldbackground=palette["entry_bg"], foreground=palette["entry_fg"])
        self.style.configure("TCombobox", fieldbackground=palette["entry_bg"], foreground=palette["entry_fg"], background=palette["panel"])
        self.style.configure("Horizontal.TScale", background=palette["bg"], troughcolor=palette["entry_bg"])
        self.style.configure("Horizontal.TProgressbar", background="#50c8ff", troughcolor=palette["entry_bg"])
        self.workspace_canvas.configure(bg=palette["bg"], highlightbackground=palette["bg"])
        for canvas in self.chart_canvases:
            self._style_chart_canvas(canvas)
        for text_widget in self.text_widgets:
            text_widget.configure(
                background=palette["log_bg"],
                foreground=palette["log_fg"],
                insertbackground=palette["text"],
                selectbackground=palette["select_bg"],
                selectforeground=palette["text"],
            )
        self._configure_log_tags()

    def _on_theme_mode_changed(self) -> None:
        self._apply_theme(save=True)
        if self.last_analysis:
            self._draw_waveform(self.last_analysis)

    def _on_theme_changed(self, _event: tk.Event | None = None) -> None:
        self.theme_mode.set(self.theme.get())
        self._on_theme_mode_changed()

    def _style_chart_canvas(self, canvas: tk.Canvas) -> None:
        palette = self._palette()
        canvas.configure(bg=palette["chart_bg"], highlightbackground=palette["chart_border"])

    def _chart_text(self) -> str:
        return self._palette()["chart_text"]

    def _configure_log_tags(self) -> None:
        if not hasattr(self, "log"):
            return
        palette = self._palette()
        self.log.tag_configure("error", foreground=palette["error"])
        self.log.tag_configure("warning", foreground=palette["warning"])
        self.log.tag_configure("success", foreground=palette["success"])
        self.log.tag_configure("info", foreground=palette["info"])

    def _log_tag(self, message: str) -> str:
        lowered = message.lower()
        if "error" in lowered or "failed" in lowered or "traceback" in lowered:
            return "error"
        if "warning" in lowered or "missing" in lowered:
            return "warning"
        if "finished" in lowered or "ready" in lowered or "success" in lowered:
            return "success"
        return "info"

    def _draw_waveform(self, analysis: AudioAnalysis) -> None:
        canvas = self.wave_canvas
        canvas.delete("all")
        self._style_chart_canvas(canvas)
        values = analysis.waveform or []
        width = self._chart_width(canvas)
        height = int(canvas["height"])
        mid = height // 2
        canvas.create_text(8, 8, text="Waveform", fill=self._chart_text(), anchor="nw")
        if not values:
            return
        for i, value in enumerate(values):
            x = int(i * width / max(1, len(values) - 1))
            amp = int(value * (height / 2 - 18))
            canvas.create_line(x, mid - amp, x, mid + amp, fill="#50c8ff")

    def _draw_density(self, per_10s: list[dict]) -> None:
        canvas = self.density_canvas
        canvas.delete("all")
        self._style_chart_canvas(canvas)
        width = self._chart_width(canvas)
        height = int(canvas["height"])
        canvas.create_text(8, 8, text="Density per 10s", fill=self._chart_text(), anchor="nw")
        if not per_10s:
            return
        max_total = max(bucket["total"] for bucket in per_10s) or 1
        bar_w = width / len(per_10s)
        for i, bucket in enumerate(per_10s):
            x0 = i * bar_w
            x1 = x0 + bar_w - 2
            y0 = height - 12 - (bucket["total"] / max_total) * (height - 34)
            canvas.create_rectangle(x0, y0, x1, height - 12, fill="#ffbf47", outline="")

    def _draw_pattern_density(self, chart: dict) -> None:
        canvas = self.pattern_canvas
        canvas.delete("all")
        self._style_chart_canvas(canvas)
        width = self._chart_width(canvas)
        height = int(canvas["height"])
        canvas.create_text(8, 8, text="Pattern Density", fill=self._chart_text(), anchor="nw")
        report = chart.get("META", {}).get("autoChartReport", {})
        preview = report.get("preview", [])
        if not preview:
            return
        max_len = max((int(item.get("length", 1)) for item in preview), default=1) or 1
        bar_w = (width - 16) / max(1, len(preview))
        for i, item in enumerate(preview):
            length = int(item.get("length", 1))
            complexity = float(item.get("intensity", 0.0))
            x0 = 8 + i * bar_w
            x1 = x0 + max(2, bar_w - 1)
            y0 = height - 10 - (length / max_len) * (height - 34)
            color = "#ff5c7a" if complexity >= 0.65 else "#c891ff" if length >= 4 else "#50c8ff"
            canvas.create_rectangle(x0, y0, x1, height - 10, fill=color, outline="")

    def _draw_layout_heatmap(self, chart: dict) -> None:
        canvas = self.layout_canvas
        canvas.delete("all")
        self._style_chart_canvas(canvas)
        width = self._chart_width(canvas)
        height = int(canvas["height"])
        canvas.create_text(8, 8, text="Layout Heatmap", fill=self._chart_text(), anchor="nw")
        report = chart.get("META", {}).get("autoChartReport", {})
        distribution = report.get("lane_distribution", {})
        if not distribution:
            return
        lanes = [str(i) for i in range(-4, 5)]
        max_count = max((int(distribution.get(lane, 0)) for lane in lanes), default=1) or 1
        cell_w = (width - 32) / len(lanes)
        for i, lane in enumerate(lanes):
            count = int(distribution.get(lane, 0))
            intensity = count / max_count
            shade = int(45 + 165 * intensity)
            fill = f"#{shade:02x}{90:02x}{210 - int(80 * intensity):02x}"
            x0 = 16 + i * cell_w
            x1 = x0 + cell_w - 3
            canvas.create_rectangle(x0, 32, x1, height - 22, fill=fill, outline="#222222")
            canvas.create_text((x0 + x1) / 2, height - 12, text=lane, fill=self._chart_text())

    def _finish_dialog(self) -> None:
        self._show_completion_dialog()

    def _style_dialog_button(self, button: tk.Button) -> None:
        palette = self._palette()
        button.configure(
            bg=palette["entry_bg"],
            fg=palette["text"],
            activebackground=palette["select_bg"],
            activeforeground=palette["text"],
            relief=tk.FLAT,
            bd=0,
            padx=14,
            pady=7,
            cursor="hand2",
        )

    def _show_completion_dialog(self) -> None:
        palette = self._palette()
        dialog = tk.Toplevel(self)
        dialog.title("Generation Finished")
        dialog.configure(bg=palette["bg"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        frame = tk.Frame(dialog, bg=palette["bg"], padx=24, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)
        title = tk.Label(frame, text="Generation Finished", bg=palette["bg"], fg=palette["text"], font=("TkDefaultFont", 13, "bold"))
        title.pack(pady=(0, 8))
        message = tk.Label(frame, text="The chart has been generated successfully.", bg=palette["bg"], fg=palette["muted"], justify=tk.CENTER)
        message.pack(pady=(0, 16))

        row = tk.Frame(frame, bg=palette["bg"])
        row.pack()
        buttons = (
            ("Open Folder", lambda: (self._open_output_folder(), dialog.destroy())),
            ("Continue Editing", dialog.destroy),
            ("Close", dialog.destroy),
        )
        for label, command in buttons:
            button = tk.Button(row, text=label, command=command)
            self._style_dialog_button(button)
            button.pack(side=tk.LEFT, padx=5)

        dialog.update_idletasks()
        width = max(380, dialog.winfo_reqwidth())
        height = max(160, dialog.winfo_reqheight())
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def _open_output_folder(self) -> None:
        target = self.last_output or Path(self.output_path.get())
        folder = target if target.is_dir() else target.parent
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)

    def _friendly_error(self, exc: Exception) -> str:
        message = str(exc)
        if "M4A decoding failed" in message:
            return "M4A decoding failed. Please check whether the audio file is valid."
        if ".m4a" in message.lower() or ".aac" in message.lower() or ".alac" in message.lower():
            return "M4A decoding failed. Please check whether the audio file is valid."
        return f"{exc.__class__.__name__}: {exc}"

    def _log(self, message: str) -> None:
        tag = self._log_tag(message)
        self.log.insert(tk.END, message + "\n", tag)
        self.log.see(tk.END)


def main() -> None:
    AutoChartGUI().mainloop()


if __name__ == "__main__":
    main()
