from __future__ import annotations

import sys
from pathlib import Path
from tkinter import messagebox

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rephi_auto_chart.chart_analyzer import analyze_chart_file, write_analysis_reports
from rephi_auto_chart.gui import main
from rephi_auto_chart.runtime import bundled_resource_path, ensure_runtime_layout, find_ffmpeg


if __name__ == "__main__":
    if "--smoke-check" in sys.argv:
        try:
            ensure_runtime_layout()
            if bundled_resource_path("config/default_config.json") is None:
                raise RuntimeError("Bundled default config was not found.")
            if find_ffmpeg() is None:
                raise RuntimeError("Bundled ffmpeg was not found.")
            raise SystemExit(0)
        except Exception:
            raise SystemExit(1)
    elif len(sys.argv) > 1 and Path(sys.argv[1]).suffix.lower() == ".pez":
        try:
            layout, _ = ensure_runtime_layout()
            target = layout.outputs / "analysis"
            result = analyze_chart_file(sys.argv[1])
            paths = write_analysis_reports(result, target)
            messagebox.showinfo(
                "Re:PhiEdit Auto Chart Assistant",
                "PEZ analysis report created:\n" + "\n".join(str(path) for path in paths.values()),
            )
        except Exception as exc:
            messagebox.showerror("Re:PhiEdit Auto Chart Assistant", f"Could not analyze PEZ file:\n{exc}")
    else:
        main()
