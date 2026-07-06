from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .analysis import AudioAnalysis, analyze_audio
from .batch import batch_generate
from .chart_analyzer import analyze_chart_file
from .config import AssistantConfig, Difficulty
from .diagnostics import run_startup_checks
from .exporter import export_pez, export_rephi_package, export_rpe_chart
from .generator import generate_chart
from .runtime import configured_export_path, default_export_path, ensure_runtime_layout, save_configured_export_path


class AutoChartGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Re:PhiEdit Auto Chart Assistant 2.4.0")
        self.geometry("1120x760")
        self.runtime_layout, self.runtime_messages = ensure_runtime_layout()
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
        self.status = tk.StringVar(value="Ready")
        self.song_info = tk.StringVar(value="No audio loaded")
        self.stats_info = tk.StringVar(value="No chart generated")
        self.phrase_info = tk.StringVar(value="No phrase data")
        self.batch_files: list[Path] = []
        self.last_output: Path | None = None
        self.last_analysis: AudioAnalysis | None = None
        self.messages: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self._build()
        self._run_startup_checks()
        self.after(100, self._drain_messages)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        top = ttk.Frame(root)
        top.pack(fill=tk.X)
        ttk.Button(top, text="Select Audio", command=self._select_audio).grid(row=0, column=0, sticky="ew")
        ttk.Entry(top, textvariable=self.audio_path).grid(row=0, column=1, columnspan=5, sticky="ew", padx=8)
        ttk.Button(top, text="Batch Select", command=self._select_batch).grid(row=0, column=6, sticky="ew")
        ttk.Label(top, text="Difficulty").grid(row=1, column=0, sticky="w", pady=8)
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
        ttk.Combobox(
            top,
            textvariable=self.chart_style,
            values=["Official-like", "Balanced", "Dense", "Experimental"],
            state="readonly",
            width=16,
        ).grid(row=3, column=2, sticky="w")
        for index, (label, value) in enumerate((("PEZ Import Package", "pez"), ("Folder Package", "folder"), ("chart.json", "json"))):
            ttk.Radiobutton(top, text=label, value=value, variable=self.output_mode, command=self._sync_output_default).grid(row=4, column=index + 1, sticky="w")
        ttk.Button(top, text="Export To", command=self._select_output).grid(row=5, column=0, sticky="ew")
        ttk.Entry(top, textvariable=self.output_path).grid(row=5, column=1, columnspan=5, sticky="ew", padx=8)
        ttk.Button(top, text="Generate", command=self._generate).grid(row=5, column=6, sticky="ew")
        ttk.Button(top, text="Open Output Folder", command=self._open_output_folder).grid(row=6, column=6, sticky="ew", pady=4)
        top.columnconfigure(3, weight=1)
        self.progress = ttk.Progressbar(root, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=6)
        ttk.Label(root, textvariable=self.status).pack(anchor="w")
        panes = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, pady=6)
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(right, weight=2)
        ttk.Label(left, text="Song Info").pack(anchor="w")
        ttk.Label(left, textvariable=self.song_info, justify=tk.LEFT).pack(anchor="w", fill=tk.X)
        self.wave_canvas = tk.Canvas(left, height=135, bg="#111111", highlightthickness=1, highlightbackground="#444")
        self.wave_canvas.pack(fill=tk.X, pady=6)
        self.density_canvas = tk.Canvas(left, height=115, bg="#111111", highlightthickness=1, highlightbackground="#444")
        self.density_canvas.pack(fill=tk.X, pady=6)
        self.pattern_canvas = tk.Canvas(left, height=90, bg="#111111", highlightthickness=1, highlightbackground="#444")
        self.pattern_canvas.pack(fill=tk.X, pady=6)
        self.layout_canvas = tk.Canvas(left, height=90, bg="#111111", highlightthickness=1, highlightbackground="#444")
        self.layout_canvas.pack(fill=tk.X, pady=6)
        self.phrase_canvas = tk.Canvas(left, height=105, bg="#111111", highlightthickness=1, highlightbackground="#444")
        self.phrase_canvas.pack(fill=tk.X, pady=6)
        self.preview_canvas = tk.Canvas(left, height=200, bg="#111111", highlightthickness=1, highlightbackground="#444")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True, pady=6)
        ttk.Label(right, text="Generation Stats").pack(anchor="w")
        ttk.Label(right, textvariable=self.stats_info, justify=tk.LEFT).pack(anchor="w", fill=tk.X)
        ttk.Label(right, text="Phrase / Quality").pack(anchor="w", pady=(12, 0))
        ttk.Label(right, textvariable=self.phrase_info, justify=tk.LEFT).pack(anchor="w", fill=tk.X)
        ttk.Label(right, text="Log").pack(anchor="w", pady=(12, 0))
        self.log = tk.Text(right, height=24)
        self.log.pack(fill=tk.BOTH, expand=True)

    def _run_startup_checks(self) -> None:
        result = run_startup_checks(Path(self.output_path.get()).parent)
        for message in result.messages:
            self._log(message)
        if not result.ok:
            messagebox.showwarning("Startup Check", "\n".join(result.messages))

    def _select_audio(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Audio", "*.wav *.mp3 *.flac *.ogg"), ("All", "*.*")])
        if path:
            self.audio_path.set(path)
            self._analyze_for_display(Path(path))

    def _select_batch(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("Audio", "*.wav *.mp3 *.flac *.ogg"), ("All", "*.*")])
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
            self.output_path.set(path)
            save_configured_export_path(path, self.runtime_layout)

    def _sync_output_default(self) -> None:
        mode = self.output_mode.get()
        path = default_export_path(mode)
        self.output_path.set(str(path))
        save_configured_export_path(path, self.runtime_layout)

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
        self.song_info.set(
            f"Length: {analysis.duration:.2f}s\nSample rate: {analysis.sample_rate} Hz\nBPM: {analysis.bpm:.2f}\n"
            f"Sections: {', '.join(label for _, _, label in analysis.sections)}"
        )
        self._draw_waveform(analysis)

    def _show_generated(self, analysis: AudioAnalysis, chart: dict, output: Path) -> None:
        report_path = output if output.suffix.lower() in {".pez", ".json"} else output / "chart.json"
        report = analyze_chart_file(report_path)
        self.status.set(f"Generation finished: {output}")
        self.stats_info.set(
            f"Tap: {report.tap_count}\nHold: {report.hold_count}\nDrag: {report.drag_count}\nFlick: {report.flick_count}\n"
            f"Total Note: {report.total_notes}\nLongest Hold: {report.longest_hold_seconds:.2f}s\n"
            f"Average Density: {report.average_density:.2f}/10s\nMax Density: {report.max_density}/10s\nNPS: {report.nps:.2f}"
        )
        auto_report = chart.get("META", {}).get("autoChartReport", {})
        if auto_report:
            ratios = auto_report.get("type_ratios", {})
            target = auto_report.get("density_target", {})
            self.stats_info.set(
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
            self.phrase_info.set(
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
        self._draw_phrases(chart)
        self._draw_preview(chart)
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

    def _draw_waveform(self, analysis: AudioAnalysis) -> None:
        canvas = self.wave_canvas
        canvas.delete("all")
        values = analysis.waveform or []
        width = max(canvas.winfo_width(), 600)
        height = int(canvas["height"])
        mid = height // 2
        canvas.create_text(8, 8, text="Waveform", fill="#eeeeee", anchor="nw")
        if not values:
            return
        for i, value in enumerate(values):
            x = int(i * width / max(1, len(values) - 1))
            amp = int(value * (height / 2 - 18))
            canvas.create_line(x, mid - amp, x, mid + amp, fill="#50c8ff")

    def _draw_density(self, per_10s: list[dict]) -> None:
        canvas = self.density_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 600)
        height = int(canvas["height"])
        canvas.create_text(8, 8, text="Density per 10s", fill="#eeeeee", anchor="nw")
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
        width = max(canvas.winfo_width(), 600)
        height = int(canvas["height"])
        canvas.create_text(8, 8, text="Pattern Density", fill="#eeeeee", anchor="nw")
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
        width = max(canvas.winfo_width(), 600)
        height = int(canvas["height"])
        canvas.create_text(8, 8, text="Layout Heatmap", fill="#eeeeee", anchor="nw")
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
            canvas.create_text((x0 + x1) / 2, height - 12, text=lane, fill="#cccccc")

    def _draw_phrases(self, chart: dict) -> None:
        canvas = self.phrase_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 600)
        height = int(canvas["height"])
        canvas.create_text(8, 8, text="Phrase Preview", fill="#eeeeee", anchor="nw")
        report = chart.get("META", {}).get("autoChartReport", {})
        preview = report.get("phrase_summary", {}).get("preview", [])
        if not preview:
            return
        max_time = max((item.get("end", 0.0) for item in preview), default=1.0) or 1.0
        colors = {
            "Tap Stream": "#50c8ff",
            "Drag Chain": "#ffbf47",
            "Hold Phrase": "#7bd88f",
            "Accent Phrase": "#ffd447",
            "Burst": "#ff5c7a",
            "Build": "#c891ff",
            "Outro": "#999999",
        }
        for item in preview:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start + 0.1))
            label = str(item.get("label", "Phrase"))
            x0 = 70 + start / max_time * (width - 90)
            x1 = max(x0 + 4, 70 + end / max_time * (width - 90))
            canvas.create_rectangle(x0, 36, x1, height - 20, fill=colors.get(label, "#888888"), outline="")
        labels = ["Tap Stream", "Drag Chain", "Hold Phrase", "Accent Phrase", "Burst", "Build"]
        for index, label in enumerate(labels):
            x = 8 + (index % 3) * 170
            y = 28 + (index // 3) * 18
            canvas.create_rectangle(x, y, x + 10, y + 10, fill=colors.get(label, "#888888"), outline="")
            canvas.create_text(x + 14, y + 5, text=label, fill="#cccccc", anchor="w")

    def _draw_preview(self, chart: dict) -> None:
        canvas = self.preview_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 600)
        height = int(canvas["height"])
        canvas.create_text(8, 8, text="2D Note Preview", fill="#eeeeee", anchor="nw")
        notes = chart["judgeLineList"][0]["notes"]
        max_beat = max((n["startTime"][0] + n["startTime"][1] / max(1, n["startTime"][2]) for n in notes), default=1)
        colors = {1: "#50c8ff", 2: "#7bd88f", 3: "#ff5c7a", 4: "#ffd447"}
        labels = {1: "Tap", 2: "Hold", 3: "Drag", 4: "Flick"}
        lanes = {1: 55, 2: 100, 3: 145, 4: 190}
        for note_type, y in lanes.items():
            canvas.create_text(8, y, text=labels[note_type], fill="#cccccc", anchor="w")
        for note in notes:
            beat = note["startTime"][0] + note["startTime"][1] / max(1, note["startTime"][2])
            x = 80 + beat / max_beat * (width - 100)
            y = lanes.get(note["type"], 55)
            if note["type"] == 2:
                end = note["endTime"][0] + note["endTime"][1] / max(1, note["endTime"][2])
                x2 = 80 + end / max_beat * (width - 100)
                canvas.create_line(x, y, x2, y, fill=colors[note["type"]], width=5)
            else:
                canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=colors.get(note["type"], "#fff"), outline="")

    def _finish_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Generation Finished")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(dialog, text="Generation Finished", padding=16).pack()
        row = ttk.Frame(dialog, padding=12)
        row.pack()
        ttk.Button(row, text="Open Folder", command=lambda: (self._open_output_folder(), dialog.destroy())).pack(side=tk.LEFT, padx=6)
        ttk.Button(row, text="Continue Editing", command=dialog.destroy).pack(side=tk.LEFT, padx=6)
        ttk.Button(row, text="Close", command=dialog.destroy).pack(side=tk.LEFT, padx=6)

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
        return f"{exc.__class__.__name__}: {exc}"

    def _log(self, message: str) -> None:
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)


def main() -> None:
    AutoChartGUI().mainloop()


if __name__ == "__main__":
    main()
