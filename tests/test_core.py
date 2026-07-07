import json
import math
import os
import re
import sys
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

from rephi_auto_chart.analysis import AudioAnalysis, SUPPORTED_EXTENSIONS, analyze_audio
import rephi_auto_chart
from rephi_auto_chart.accent import detect_accent_at
from rephi_auto_chart.batch import batch_generate
from rephi_auto_chart.chart_analyzer import analyze_chart_file, write_analysis_reports
from rephi_auto_chart.compare import compare_charts, write_comparison_reports
from rephi_auto_chart.config import AssistantConfig, Difficulty
from rephi_auto_chart.diagnostics import run_startup_checks
from rephi_auto_chart.exporter import export_pez, export_rephi_package, export_rpe_chart, load_rpe_chart
from rephi_auto_chart.generator import generate_chart
from rephi_auto_chart.parser import inspect_rephi_install
from rephi_auto_chart.patterns import pattern_names
from rephi_auto_chart.pattern_generator import pattern_library_names
from rephi_auto_chart.layout import compute_layout_report
from rephi_auto_chart.runtime import audio_default_export_path, bundled_resource_path, configured_export_path, default_export_path, ensure_runtime_layout, read_runtime_config, safe_export_filename_stem, safe_output_dir, save_configured_export_path, write_runtime_config
from rephi_auto_chart.timebase import beat_tuple_to_beats
from rephi_auto_chart.validator import detect_notes_inside_holds, validate_and_fix_chart


def write_click_track(path: Path, bpm: float = 120.0, seconds: float = 8.0) -> None:
    sample_rate = 44100
    total = int(seconds * sample_rate)
    beat_interval = 60.0 / bpm
    click_len = int(0.025 * sample_rate)
    samples = [0] * total
    for beat in range(int(seconds / beat_interval)):
        start = int(beat * beat_interval * sample_rate)
        for i in range(click_len):
            idx = start + i
            if idx < total:
                env = 1.0 - (i / click_len)
                samples[idx] = int(28000 * env * math.sin(2 * math.pi * 1000 * i / sample_rate))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"".join(int(s).to_bytes(2, "little", signed=True) for s in samples))


def write_pattern_song(path: Path, bpm: float = 132.0, seconds: float = 14.0) -> None:
    sample_rate = 44100
    total = int(seconds * sample_rate)
    beat_interval = 60.0 / bpm
    samples = [0] * total
    for idx in range(total):
        t = idx / sample_rate
        sustain = 0.22 * math.sin(2 * math.pi * 220 * t) + 0.12 * math.sin(2 * math.pi * 330 * t)
        samples[idx] += int(10000 * sustain)
    for beat in range(int(seconds / beat_interval)):
        start = int(beat * beat_interval * sample_rate)
        click_len = int((0.035 if beat % 4 == 0 else 0.022) * sample_rate)
        freq = 880 if beat % 4 == 0 else 1320
        amp = 25000 if beat % 4 == 0 else 16000
        for i in range(click_len):
            index = start + i
            if index < total:
                env = 1.0 - i / click_len
                samples[index] += int(amp * env * math.sin(2 * math.pi * freq * i / sample_rate))
    _write_pcm16(path, samples, sample_rate)


def write_high_energy_track(path: Path, bpm: float = 168.0, seconds: float = 14.0) -> None:
    sample_rate = 44100
    total = int(seconds * sample_rate)
    beat_interval = 60.0 / bpm
    samples = [0] * total
    for beat in range(int(seconds / beat_interval)):
        for offset, freq, amp, length in ((0.0, 90, 30000, 0.04), (0.5, 1800, 15000, 0.018), (0.75, 3600, 9500, 0.012)):
            start = int((beat + offset) * beat_interval * sample_rate)
            click_len = int(length * sample_rate)
            for i in range(click_len):
                index = start + i
                if index < total:
                    env = 1.0 - i / max(1, click_len)
                    samples[index] += int(amp * env * math.sin(2 * math.pi * freq * i / sample_rate))
    _write_pcm16(path, samples, sample_rate)


def _write_pcm16(path: Path, samples: list[int], sample_rate: int) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        clipped = [max(-32768, min(32767, value)) for value in samples]
        wav.writeframes(b"".join(int(s).to_bytes(2, "little", signed=True) for s in clipped))


def _note_count(chart: dict) -> int:
    return len(chart["judgeLineList"][0]["notes"])


def _note_seconds(note: dict, bpm: float) -> float:
    return beat_tuple_to_beats(note["startTime"]) * 60.0 / bpm


def _type_ratio(chart: dict, note_type: int) -> float:
    notes = chart["judgeLineList"][0]["notes"]
    return sum(1 for note in notes if note["type"] == note_type) / max(1, len(notes))


class CoreFlowTests(unittest.TestCase):
    def test_audio_analysis_detects_click_track_bpm_and_onsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "clicks.wav"
            write_click_track(audio, bpm=120.0)
            result = analyze_audio(audio)
        self.assertGreaterEqual(len(result.onsets), 8)
        self.assertAlmostEqual(result.bpm, 120.0, delta=8.0)
        self.assertGreater(result.duration, 7.9)

    def test_generate_chart_uses_supported_note_types_without_forcing_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "clicks.wav"
            write_click_track(audio, bpm=150.0, seconds=12.0)
            analysis = analyze_audio(audio)
            chart = generate_chart(
                analysis,
                AssistantConfig(difficulty=Difficulty.AT, overall_density=1.25),
                song_filename="clicks.wav",
            )
        types = {note["type"] for note in chart["judgeLineList"][0]["notes"]}
        self.assertTrue({1, 3, 4}.issubset(types))
        self.assertLessEqual(_type_ratio(chart, 2), 0.12)
        self.assertEqual(len(chart["judgeLineList"]), 1)
        self.assertEqual(chart["judgeLineList"][0]["eventLayers"][0]["speedEvents"], [])

    def test_validator_repairs_negative_time_and_hold_order(self):
        chart = {
            "BPMList": [{"bpm": 120.0, "startTime": [0, 0, 1]}],
            "META": {},
            "judgeLineGroup": ["Default"],
            "judgeLineList": [
                {
                    "notes": [
                        {
                            "type": 2,
                            "startTime": [-1, 0, 1],
                            "endTime": [-2, 0, 1],
                            "positionX": 900,
                            "above": 1,
                            "isFake": 0,
                            "alpha": 255,
                            "size": 1.0,
                            "speed": 1.0,
                            "visibleTime": 999999.0,
                            "yOffset": 0.0,
                        }
                    ],
                    "eventLayers": [{"alphaEvents": [], "moveXEvents": [], "moveYEvents": [], "rotateEvents": [], "speedEvents": []}],
                }
            ],
        }
        fixed, report = validate_and_fix_chart(chart)
        note = fixed["judgeLineList"][0]["notes"][0]
        self.assertEqual(note["startTime"], [0, 0, 1])
        self.assertGreaterEqual(note["endTime"][0], note["startTime"][0])
        self.assertLessEqual(abs(note["positionX"]), 675)
        self.assertGreater(report.fixed_count, 0)

    def test_export_and_reload_rpe_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "clicks.wav"
            output = Path(tmp) / "chart.json"
            write_click_track(audio, bpm=120.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.HD), "clicks.wav")
            export_rpe_chart(chart, output)
            loaded = load_rpe_chart(output)
        self.assertIn("BPMList", loaded)
        self.assertIn("judgeLineList", loaded)

    def test_export_rephi_package_includes_default_illustration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "clicks.wav"
            package = root / "package"
            write_click_track(audio, bpm=120.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.HD), "clicks.wav")
            export_rephi_package(chart, package, audio)
            loaded = load_rpe_chart(package / "chart.json")
            info = (package / "info.txt").read_text(encoding="utf-8")
            self.assertTrue((package / "chart.json").exists())
            self.assertTrue((package / "info.txt").exists())
            self.assertTrue((package / "clicks.wav").exists())
            self.assertTrue((package / "illustration.png").exists())
            self.assertEqual(loaded["META"]["background"], "illustration.png")
            self.assertIn("Picture: illustration.png", info)

    def test_export_pez_matches_rephi_zip_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "clicks.wav"
            output = root / "auto.pez"
            write_click_track(audio, bpm=120.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.HD), "clicks.wav")
            export_pez(chart, output, audio)
            self.assertTrue(zipfile.is_zipfile(output))
            with zipfile.ZipFile(output) as zf:
                names = sorted(zf.namelist())
                info = zf.read("info.txt").decode("utf-8")
                chart_name = next(name for name in names if name.endswith(".json"))
                loaded = json.loads(zf.read(chart_name).decode("utf-8"))
            self.assertIn("info.txt", names)
            self.assertTrue(any(name.endswith(".wav") for name in names))
            self.assertTrue(any(name.endswith(".png") for name in names))
            self.assertIn(f"Chart: {chart_name}", info)
            self.assertEqual(loaded["META"]["background"], "auto.png")
            self.assertEqual(loaded["META"]["id"], "auto")

    def test_density_scaling(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio)
            analysis = analyze_audio(audio)
            counts = {}
            for difficulty in Difficulty:
                chart = generate_chart(analysis, AssistantConfig(difficulty=difficulty), "high_energy.wav")
                counts[difficulty.value] = _note_count(chart)
        self.assertLess(counts["EZ"], counts["HD"])
        self.assertLess(counts["HD"], counts["IN"])
        self.assertLess(counts["IN"], counts["AT"])
        self.assertGreaterEqual(counts["AT"], int(counts["IN"] * 1.25))

    def test_offset_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "clicks.wav"
            write_click_track(audio, bpm=120.0, seconds=8.0)
            analysis = analyze_audio(audio)
            base = generate_chart(
                analysis,
                AssistantConfig(difficulty=Difficulty.HD, auto_timing_calibration=False, manual_offset_ms=0, snap_strength=0),
                "clicks.wav",
            )
            shifted = generate_chart(
                analysis,
                AssistantConfig(difficulty=Difficulty.HD, auto_timing_calibration=False, manual_offset_ms=100, snap_strength=0),
                "clicks.wav",
            )
        base_first = _note_seconds(base["judgeLineList"][0]["notes"][0], analysis.bpm)
        shifted_first = _note_seconds(shifted["judgeLineList"][0]["notes"][0], analysis.bpm)
        self.assertAlmostEqual(shifted_first - base_first, 0.1, delta=0.035)
        self.assertEqual(shifted["META"]["autoChartReport"]["manual_offset_ms"], 100.0)

    def test_note_type_distribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "pattern.wav"
            write_pattern_song(audio)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), "pattern.wav")
        types = [note["type"] for note in chart["judgeLineList"][0]["notes"]]
        self.assertGreaterEqual(types.count(1), 1)
        self.assertGreaterEqual(types.count(3), 1)
        self.assertGreaterEqual(types.count(4), 1)
        self.assertLessEqual(types.count(2), len(types) * 0.12)
        self.assertGreater(types.count(1) + types.count(3) + types.count(4), types.count(2) * 4)
        self.assertLess(types.count(4), len(types) * 0.35)

    def test_accent_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=160.0, seconds=8.0)
            analysis = analyze_audio(audio)
        strong = max((detect_accent_at(analysis, onset) for onset in analysis.onsets[:8]), key=lambda item: item.accent_score)
        weak = detect_accent_at(analysis, strong.time + 0.30)
        self.assertGreater(strong.accent_score, weak.accent_score)
        for value in (strong.accent_score, strong.kick_score, strong.snare_score, strong.hat_score, strong.energy_score, strong.onset_score):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_pez_export_still_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "pattern.wav"
            output = root / "v21.pez"
            write_pattern_song(audio)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.IN), "pattern.wav")
            export_pez(chart, output, audio)
            with zipfile.ZipFile(output) as zf:
                names = zf.namelist()
                self.assertIn("info.txt", names)
                self.assertTrue(any(name.endswith(".json") for name in names))
                self.assertTrue(any(name.endswith(".wav") for name in names))
                self.assertTrue(any(name.endswith(".png") for name in names))
                chart_name = next(name for name in names if name.endswith(".json"))
                loaded = json.loads(zf.read(chart_name).decode("utf-8"))
        self.assertEqual(loaded["META"]["RPEVersion"], 113)
        self.assertIn("autoChartReport", loaded["META"])

    def test_bpm_aware_density(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=150.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), "high_energy.wav")
        target = chart["META"]["autoChartReport"]["density_target"]
        self.assertGreater(target["total_beats"], 20)
        self.assertGreater(target["target_notes_from_bpm"], 0)
        self.assertGreater(target["target_notes_from_onsets"], 0)
        self.assertGreater(target["target_notes_final"], 0)
        self.assertEqual(target["actual_notes"], chart["META"]["autoChartReport"]["note_count"])

    def test_density_scales_with_bpm_and_length(self):
        counts = {}
        with tempfile.TemporaryDirectory() as tmp:
            for label, bpm, seconds in (("slow_short", 100.0, 10.0), ("fast_long", 180.0, 18.0)):
                audio = Path(tmp) / f"{label}.wav"
                write_high_energy_track(audio, bpm=bpm, seconds=seconds)
                chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), audio.name)
                counts[label] = _note_count(chart)
        self.assertNotEqual(counts["slow_short"], 80)
        self.assertNotEqual(counts["fast_long"], 80)
        self.assertGreater(counts["fast_long"], counts["slow_short"])

    def test_drag_ratio_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=168.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), "high_energy.wav")
        report = chart["META"]["autoChartReport"]
        self.assertLessEqual(report["type_ratios"]["drag"], 0.16)
        self.assertLessEqual(_type_ratio(chart, 3), 0.16)

    def test_tap_is_default_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "clicks.wav"
            write_click_track(audio, bpm=150.0, seconds=12.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), "clicks.wav")
        self.assertGreater(_type_ratio(chart, 1), 0.55)
        self.assertLess(_type_ratio(chart, 3), 0.16)

    def test_density_filler_not_random(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=170.0, seconds=12.0)
            analysis = analyze_audio(audio)
            config = AssistantConfig(difficulty=Difficulty.AT, overall_density=1.25)
            first = generate_chart(analysis, config, "high_energy.wav")
            second = generate_chart(analysis, config, "high_energy.wav")
        first_times = [note["startTime"] for note in first["judgeLineList"][0]["notes"]]
        second_times = [note["startTime"] for note in second["judgeLineList"][0]["notes"]]
        self.assertEqual(first_times, second_times)
        self.assertTrue(first["META"]["autoChartReport"]["density_filler_summary"]["added_notes"] >= 0)

    def test_note_type_reason_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "pattern.wav"
            write_pattern_song(audio)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.IN), "pattern.wav")
        debug = chart["META"]["autoChartReport"]["note_type_debug"]
        self.assertTrue(debug)
        first = debug[0]
        for key in ("selected_type", "type_reason", "tap_score", "hold_score", "flick_score", "drag_score"):
            self.assertIn(key, first)

    def test_difficulty_ordering(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "pattern.wav"
            write_pattern_song(audio, bpm=132.0, seconds=16.0)
            analysis = analyze_audio(audio)
            counts = {difficulty.value: _note_count(generate_chart(analysis, AssistantConfig(difficulty=difficulty), audio.name)) for difficulty in Difficulty}
        self.assertLess(counts["EZ"], counts["HD"])
        self.assertLess(counts["HD"], counts["IN"])
        self.assertLess(counts["IN"], counts["AT"])

    def test_drag_chain_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=168.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT, chart_style="Balanced"), audio.name)
        summary = chart["META"]["autoChartReport"]["phrase_summary"]
        self.assertGreaterEqual(summary["drag_chain_count"], 1)
        self.assertGreaterEqual(summary["longest_drag_chain"], 2)
        self.assertLessEqual(summary["longest_drag_chain"], 12)

    def test_phrase_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "pattern.wav"
            write_pattern_song(audio, bpm=132.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.IN), audio.name)
        summary = chart["META"]["autoChartReport"]["phrase_summary"]
        self.assertGreater(summary["phrase_count"], 3)
        self.assertTrue(summary["preview"])
        self.assertIn("label", summary["preview"][0])

    def test_pattern_library(self):
        names = set(pattern_names())
        required = {
            "Tap Stream",
            "Alternating",
            "Double",
            "Triple",
            "Stair",
            "Burst",
            "Drag Chain",
            "Jack",
            "Trill",
            "Wave",
            "Jump",
            "Center Expand",
            "Center Close",
            "Drop Pattern",
            "Build Pattern",
            "Outro Pattern",
        }
        self.assertTrue(required.issubset(names))

    def test_quality_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=168.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), audio.name)
        score = chart["META"]["autoChartReport"]["quality_score"]
        for key in ("Density", "Timing", "Pattern Diversity", "Phrase Quality", "Type Balance", "Readability", "Flow", "Overall"):
            self.assertIn(key, score)
            self.assertGreaterEqual(score[key], 0)
            self.assertLessEqual(score[key], 100)

    def test_phrase_diversity(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=168.0, seconds=18.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT, chart_style="Dense"), audio.name)
        summary = chart["META"]["autoChartReport"]["phrase_summary"]
        self.assertGreaterEqual(len(summary["counts"]), 2)
        self.assertGreaterEqual(len(summary["patterns_used"]), 2)

    def test_official_like_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=168.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT, chart_style="Official-like"), audio.name)
        report = chart["META"]["autoChartReport"]
        self.assertGreater(report["type_ratios"]["tap"], 0.70)
        self.assertLessEqual(report["type_ratios"]["drag"], 0.16)
        self.assertGreaterEqual(report["quality_score"]["Overall"], 70)

    def test_style_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=168.0, seconds=16.0)
            analysis = analyze_audio(audio)
            official = generate_chart(analysis, AssistantConfig(difficulty=Difficulty.AT, chart_style="Official-like"), audio.name)
            dense = generate_chart(analysis, AssistantConfig(difficulty=Difficulty.AT, chart_style="Experimental"), audio.name)
        off = official["META"]["autoChartReport"]
        exp = dense["META"]["autoChartReport"]
        self.assertNotEqual(off["density_target"]["target_notes_final"], exp["density_target"]["target_notes_final"])
        self.assertGreaterEqual(exp["phrase_summary"]["drag_chain_count"], off["phrase_summary"]["drag_chain_count"])

    def test_pez_export_v23(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "high_energy.wav"
            output = root / "v23.pez"
            write_high_energy_track(audio)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), audio.name)
            export_pez(chart, output, audio)
            with zipfile.ZipFile(output) as zf:
                names = zf.namelist()
                chart_name = next(name for name in names if name.endswith(".json"))
                loaded = json.loads(zf.read(chart_name).decode("utf-8"))
        self.assertIn("phrase_summary", loaded["META"]["autoChartReport"])
        self.assertIn("quality_score", loaded["META"]["autoChartReport"])

    def test_release_packaging_files_exist(self):
        root = Path(__file__).resolve().parents[1]
        required = [
            root / "build_release.bat",
            root / "scripts" / "build_release.ps1",
            root / "release_check.ps1",
            root / "installer" / "inno_setup.iss",
            root / "packaging" / "windows" / "version_info.txt",
            root / "assets" / "windows" / "app_icon.ico",
        ]
        self.assertTrue(all(path.exists() for path in required))

    def test_release_metadata_is_current(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(rephi_auto_chart.__version__, "2.5.1")
        version_info = (root / "packaging" / "windows" / "version_info.txt").read_text(encoding="utf-8")
        installer = (root / "installer" / "inno_setup.iss").read_text(encoding="utf-8")
        self.assertIn("ProductVersion', '2.5.1", version_info)
        self.assertIn('#define MyAppVersion "2.5.1"', installer)
        self.assertIn("OutputBaseFilename=Setup", installer)

    def test_installer_has_professional_release_checks(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / "installer" / "inno_setup.iss").read_text(encoding="utf-8")
        for expected in (
            "MinVersion=10.0",
            "ArchitecturesAllowed=x64compatible",
            "IsVCRuntimeInstalled",
            "CheckWritable",
            "autodesktop",
            "autoprograms",
            "associatepez",
            "UninstallDisplayName",
            "SetupIconFile",
        ):
            self.assertIn(expected, installer)
        spec = (root / "packaging" / "windows" / "RePhiEditAutoChartAssistant.spec").read_text(encoding="utf-8")
        release_check = (root / "release_check.ps1").read_text(encoding="utf-8")
        for dependency in ("numpy", "scipy", "soundfile", "librosa", "PIL", "matplotlib", "numba", "soxr"):
            self.assertIn(dependency, spec)
        for excluded in ("numpy.f2py.tests", "numpy.tests", "scipy.tests", "librosa.tests", "matplotlib.tests", "pytest"):
            self.assertIn(excluded, spec)
        self.assertIn("python*.dll", release_check)
        self.assertIn("_internal", release_check)
        self.assertIn("Resolve-PortableBundledFile", release_check)
        self.assertIn("Runtime supports PyInstaller _MEIPASS resources", release_check)
        build_bat = (root / "build_release.bat").read_text(encoding="utf-8")
        build_all_bat = (root / "build_all_windows.bat").read_text(encoding="utf-8")
        build_ps1 = (root / "scripts" / "build_release.ps1").read_text(encoding="utf-8")
        exe_ps1 = (root / "scripts" / "build_windows_exe.ps1").read_text(encoding="utf-8")
        self.assertIn("Normal incremental build", build_bat)
        self.assertIn("Clean rebuild", build_bat)
        self.assertIn("Normal incremental build", build_all_bat)
        self.assertIn("Clean rebuild", build_all_bat)
        self.assertIn("--smoke-check", release_check)
        self.assertIn("without relying on current working directory", release_check)
        self.assertIn("[switch]$Clean", build_ps1)
        self.assertIn("preserving .venv-windows-build", build_ps1)
        self.assertIn("[hashtable]$NamedArguments", build_ps1)
        self.assertIn("@{ ReleaseDir = $ReleaseDir }", build_ps1)
        self.assertIn("Release directory does not exist before release checks", build_ps1)
        self.assertNotIn('@("-ReleaseDir", $ReleaseDir)', build_ps1)
        self.assertNotIn("@('-ReleaseDir', $ReleaseDir)", build_ps1)
        self.assertIn("[CmdletBinding()]", release_check)
        self.assertIn("exit 0", release_check)
        self.assertIn("ReleaseDir value looks like a switch name", release_check)
        self.assertIn("GUI does not default to relative outputs", release_check)
        self.assertIn("Bundled config does not default to relative outputs", release_check)
        self.assertIn("Runtime defines Documents chart export folder", release_check)
        self.assertIn("[switch]$Clean", exe_ps1)
        self.assertIn("Test-VenvPython312", exe_ps1)
        self.assertIn("function Invoke-Native", exe_ps1)
        self.assertNotIn("pip show", exe_ps1)

    def test_inno_filesystem_paths_use_safe_names(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / "installer" / "inno_setup.iss").read_text(encoding="utf-8")
        self.assertIn('#define MyAppDisplayName "Re:PhiEdit Auto Chart Assistant"', installer)
        self.assertIn('#define MyAppSafeName "RePhiEdit Auto Chart Assistant"', installer)
        self.assertIn("AppName={#MyAppDisplayName}", installer)
        self.assertIn("UninstallDisplayName={#MyAppDisplayName}", installer)

        path_bearing_patterns = (
            r"^DefaultDirName=.*$",
            r"^DefaultGroupName=.*$",
            r"^OutputBaseFilename=.*$",
            r"^SetupIconFile=.*$",
            r"^UninstallDisplayIcon=.*$",
            r"^Source: .*$",
            r"^Name: .*$",
            r"^Root: .*Subkey: .*$",
            r"^Filename: .*$",
            r"^Type: filesandordirs; Name: .*$",
        )
        path_lines: list[str] = []
        for pattern in path_bearing_patterns:
            path_lines.extend(re.findall(pattern, installer, flags=re.MULTILINE))
        self.assertTrue(path_lines)
        for line in path_lines:
            path_part = line.split("; Comment:", 1)[0].split("; ValueData:", 1)[0].split("; Description:", 1)[0]
            self.assertNotIn("{#MyAppDisplayName}", path_part, line)
            self.assertNotIn("Re:PhiEdit", path_part, line)
            self.assertNotRegex(path_part, r"[?<>|]", line)

        self.assertIn("DefaultDirName={autopf}\\{#MyAppSafeName}", installer)
        self.assertIn("DefaultGroupName={#MyAppSafeName}", installer)
        self.assertIn('Name: "{autoprograms}\\{#MyAppSafeName}"', installer)
        self.assertIn('Name: "{autodesktop}\\{#MyAppSafeName}"', installer)
        self.assertIn('Comment: "{#MyAppDisplayName}"', installer)

    def test_runtime_uses_localappdata_and_documents_exports(self):
        original_localappdata = os.environ.get("LOCALAPPDATA")
        original_userprofile = os.environ.get("USERPROFILE")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["LOCALAPPDATA"] = str(root / "localappdata")
            os.environ["USERPROFILE"] = str(root / "profile")
            try:
                layout, _ = ensure_runtime_layout()
                self.assertEqual(layout.root, root / "localappdata" / "RePhiEditAutoChart")
                self.assertEqual(layout.export_root, root / "profile" / "Documents" / "RePhiEdit Charts")
                self.assertTrue(layout.config.exists())
                self.assertTrue(layout.cache.exists())
                self.assertTrue(layout.logs.exists())
                self.assertTrue(layout.outputs.exists())
                self.assertTrue(layout.temp.exists())
                self.assertTrue(layout.export_root.exists())
                self.assertEqual(default_export_path("pez"), layout.export_root / "generated.pez")
            finally:
                if original_localappdata is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = original_localappdata
                if original_userprofile is None:
                    os.environ.pop("USERPROFILE", None)
                else:
                    os.environ["USERPROFILE"] = original_userprofile

    def test_relative_outputs_are_migrated_to_documents_export_folder(self):
        original_localappdata = os.environ.get("LOCALAPPDATA")
        original_userprofile = os.environ.get("USERPROFILE")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["LOCALAPPDATA"] = str(root / "localappdata")
            os.environ["USERPROFILE"] = str(root / "profile")
            try:
                layout, _ = ensure_runtime_layout()
                save_configured_export_path("outputs/generated.pez", layout)
                self.assertEqual(configured_export_path("pez", layout), layout.export_root / "generated.pez")
                self.assertEqual(safe_output_dir("outputs", layout), layout.export_root)
                custom = layout.export_root / "Custom.pez"
                save_configured_export_path(custom, layout)
                self.assertEqual(configured_export_path("pez", layout), custom)
            finally:
                if original_localappdata is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = original_localappdata
                if original_userprofile is None:
                    os.environ.pop("USERPROFILE", None)
                else:
                    os.environ["USERPROFILE"] = original_userprofile

    def test_release_gui_does_not_default_to_relative_outputs(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        default_config = json.loads((root / "config" / "default_config.json").read_text(encoding="utf-8"))
        self.assertNotIn('"outputs/generated.pez"', gui_source)
        self.assertNotIn('"outputs/generated_chart.json"', gui_source)
        self.assertEqual(default_config.get("export_path", ""), "")

    def test_runtime_finds_pyinstaller_internal_default_config(self):
        original_meipass = getattr(sys, "_MEIPASS", None)
        had_meipass = hasattr(sys, "_MEIPASS")
        original_localappdata = os.environ.get("LOCALAPPDATA")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled_config = root / "config" / "default_config.json"
            bundled_config.parent.mkdir(parents=True)
            bundled_config.write_text(json.dumps({"difficulty": "AT", "chart_name": "Bundled"}, indent=2), encoding="utf-8")
            os.environ["LOCALAPPDATA"] = str(root / "localappdata")
            sys._MEIPASS = str(root)
            try:
                self.assertEqual(bundled_resource_path("config/default_config.json"), bundled_config)
                layout, _ = ensure_runtime_layout()
                copied = json.loads(layout.config_file.read_text(encoding="utf-8"))
                self.assertEqual(copied["difficulty"], "AT")
                self.assertEqual(copied["chart_name"], "Bundled")
            finally:
                if had_meipass:
                    sys._MEIPASS = original_meipass
                else:
                    delattr(sys, "_MEIPASS")
                if original_localappdata is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = original_localappdata


    def test_gui_default_export_uses_audio_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            export_root = Path(tmp) / "Documents" / "RePhiEdit Charts"
            export_root.mkdir(parents=True)
            audio = Path(tmp) / "Phigros Devotion.mp3"
            audio.write_bytes(b"not real audio")
            output = audio_default_export_path(audio, "pez", export_root=export_root)
        self.assertEqual(output.name, "Phigros Devotion.pez")
        self.assertEqual(output.parent.name, "RePhiEdit Charts")

    def test_safe_export_filename(self):
        self.assertEqual(safe_export_filename_stem('A:B*C?D"E<F>G|'), "A_B_C_D_E_F_G")
        self.assertEqual(safe_export_filename_stem('  ...  '), "generated")
        with tempfile.TemporaryDirectory() as tmp:
            export_root = Path(tmp)
            (export_root / "Song.pez").write_text("exists", encoding="utf-8")
            output = audio_default_export_path(Path("Song.m4a"), "pez", export_root=export_root)
        self.assertEqual(output.name, "Song_1.pez")

    def test_m4a_extension_supported(self):
        self.assertIn(".m4a", SUPPORTED_EXTENSIONS)
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("*.m4a", gui_source)
        self.assertIn("M4A", readme)

    def test_sections_summary_or_scrollable_display(self):
        from rephi_auto_chart.gui import format_song_info

        analysis = AudioAnalysis(
            Path("song.wav"),
            44100,
            12.0,
            128.0,
            [],
            [],
            [],
            [(0.0, 2.0, "Intro"), (2.0, 4.0, "Intro"), (4.0, 6.0, "Verse"), (6.0, 8.0, "Verse"), (8.0, 10.0, "Drop")],
            [],
        )
        text = format_song_info(analysis)
        self.assertIn("Sections: Intro x2, Verse x2, Drop x1", text)
        self.assertNotIn("Sections Full:", text)

    def test_log_scrollbar_exists_or_log_widget_scrollable(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("self.log = ScrolledText", gui_source)
        self.assertIn("self.log.see(tk.END)", gui_source)
        self.assertIn("xscrollcommand", gui_source)
        self.assertIn("self.sections_summary_label", gui_source)

    def test_version_242_consistency_legacy_hotfix_coverage(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(rephi_auto_chart.__version__, "2.5.1")
        self.assertEqual((root / "VERSION").read_text(encoding="utf-8").strip(), "2.5.1")
        version_info = (root / "packaging" / "windows" / "version_info.txt").read_text(encoding="utf-8")
        installer = (root / "installer" / "inno_setup.iss").read_text(encoding="utf-8")
        release_check = (root / "release_check.ps1").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("ProductVersion', '2.5.1", version_info)
        self.assertIn('#define MyAppVersion "2.5.1"', installer)
        self.assertIn("2.5.1", release_check)
        self.assertIn("V2.5.1", readme)


    def test_v242_stats_widget_scrollable(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("from tkinter.scrolledtext import ScrolledText", gui_source)
        self.assertIn("self.stats_text = ScrolledText", gui_source)
        self.assertIn("wrap=tk.NONE", gui_source)
        self.assertIn("_set_stats_text", gui_source)
        self.assertNotIn("textvariable=self.stats_info", gui_source)

    def test_v242_log_widget_scrollable(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("self.log = ScrolledText", gui_source)
        self.assertIn("height=9", gui_source)
        self.assertIn("self.log.see(tk.END)", gui_source)
        self.assertNotIn("self.log_scrollbar", gui_source)

    def test_v242_chart_container_scrollable(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("def _create_chart_card", gui_source)
        self.assertIn("xscrollcommand=scrollbar.set", gui_source)
        self.assertIn("scrollregion=(0, 0, CHART_CANVAS_WIDTH", gui_source)
        for name in ("wave_canvas", "density_canvas", "pattern_canvas", "layout_canvas"):
            self.assertIn(f"self.{name} = self._create_chart_card", gui_source)

    def test_v242_window_min_size(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("self.minsize(1000, 700)", gui_source)
        self.assertIn("self.workspace_canvas = tk.Canvas", gui_source)
        self.assertIn("self.output_notebook = ttk.Notebook", gui_source)

    def test_version_242_consistency(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(rephi_auto_chart.__version__, "2.5.1")
        self.assertEqual((root / "VERSION").read_text(encoding="utf-8").strip(), "2.5.1")
        version_info = (root / "packaging" / "windows" / "version_info.txt").read_text(encoding="utf-8")
        installer = (root / "installer" / "inno_setup.iss").read_text(encoding="utf-8")
        release_check = (root / "release_check.ps1").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("ProductVersion', '2.5.1", version_info)
        self.assertIn('#define MyAppVersion "2.5.1"', installer)
        self.assertIn("2.5.1", release_check)
        self.assertIn("V2.5.1", readme)


    def test_v250_workspace_scrollable(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("self.workspace_canvas = tk.Canvas", gui_source)
        self.assertIn("self.workspace_scrollbar", gui_source)
        self.assertIn("self.workspace_window", gui_source)
        self.assertIn("yscrollcommand=self.workspace_scrollbar.set", gui_source)
        self.assertIn("_update_workspace_scrollregion", gui_source)
        self.assertNotIn("body_panes = ttk.Panedwindow", gui_source)

    def test_v250_stats_log_tabs_exist(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("self.output_notebook = ttk.Notebook", gui_source)
        self.assertIn("self.stats_tab", gui_source)
        self.assertIn("self.log_tab", gui_source)
        self.assertIn('text="Stats"', gui_source)
        self.assertIn('text="Log"', gui_source)
        self.assertIn("self.log = ScrolledText", gui_source)
        self.assertIn("self.stats_text = ScrolledText", gui_source)

    def test_v250_sections_compact_summary(self):
        from rephi_auto_chart.gui import format_full_sections, format_song_info

        analysis = AudioAnalysis(
            Path("song.wav"),
            44100,
            152.71,
            113.45,
            [],
            [],
            [],
            [(0.0, 2.0, "Intro"), (2.0, 4.0, "Intro"), (4.0, 6.0, "Verse"), (6.0, 8.0, "Verse"), (8.0, 10.0, "Outro")],
            [],
        )
        compact = format_song_info(analysis)
        self.assertIn("Length: 152.71s | BPM: 113.45 | Sample Rate: 44100 Hz", compact)
        self.assertIn("Sections: Intro x2, Verse x2, Outro x1", compact)
        self.assertNotIn("Sections Full", compact)
        self.assertIn("Intro, Intro, Verse, Verse, Outro", format_full_sections(analysis.sections))

    def test_v250_full_sections_toggle(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("self.show_full_sections", gui_source)
        self.assertIn("_toggle_full_sections", gui_source)
        self.assertIn("Show Full Sections", gui_source)
        self.assertIn("Hide Full Sections", gui_source)

    def test_v250_chart_workspace_contains_four_charts(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        for attr in ("wave_canvas", "density_canvas", "pattern_canvas", "layout_canvas"):
            self.assertIn(f"self.{attr} = self._create_chart_card", gui_source)
        self.assertIn('"Waveform"', gui_source)
        self.assertIn('"Density per 10s"', gui_source)
        self.assertIn('"Pattern Density"', gui_source)
        self.assertIn('"Layout Heatmap"', gui_source)

    def test_v250_no_algorithm_files_modified_unnecessarily(self):
        root = Path(__file__).resolve().parents[1]
        forbidden_files = [
            "generator.py",
            "pattern_generator.py",
            "layout.py",
            "validator.py",
            "exporter.py",
            "chart_analyzer.py",
            "compare.py",
            "batch.py",
        ]
        for filename in forbidden_files:
            source = (root / "rephi_auto_chart" / filename).read_text(encoding="utf-8")
            self.assertNotIn("V2.5.1", source)
            self.assertNotIn("Theme", source)
            self.assertNotIn("Chart Workspace", source)

    def test_version_250_consistency(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(rephi_auto_chart.__version__, "2.5.1")
        self.assertEqual((root / "VERSION").read_text(encoding="utf-8").strip(), "2.5.1")
        version_info = (root / "packaging" / "windows" / "version_info.txt").read_text(encoding="utf-8")
        installer = (root / "installer" / "inno_setup.iss").read_text(encoding="utf-8")
        release_check = (root / "release_check.ps1").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("ProductVersion', '2.5.1", version_info)
        self.assertIn('#define MyAppVersion "2.5.1"', installer)
        self.assertIn("2.5.1", release_check)
        self.assertIn("V2.5.1", readme)

    def test_dark_theme_exists(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("THEME_PALETTES", gui_source)
        self.assertIn('"light"', gui_source)
        self.assertIn('"dark"', gui_source)
        self.assertIn("self.theme = tk.StringVar", gui_source)
        self.assertIn("_apply_theme", gui_source)
        self.assertIn("_on_theme_changed", gui_source)

    def test_theme_persistence(self):
        from rephi_auto_chart.runtime import configured_theme, save_configured_theme

        original_localappdata = os.environ.get("LOCALAPPDATA")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "localappdata")
            try:
                layout, _ = ensure_runtime_layout()
                save_configured_theme("dark", layout)
                self.assertEqual(configured_theme(layout), "dark")
                save_configured_theme("light", layout)
                self.assertEqual(configured_theme(layout), "light")
            finally:
                if original_localappdata is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = original_localappdata

    def test_dark_chart_palette(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn('"chart_bg": "#1e1e1e"', gui_source)
        self.assertIn('"chart_border": "#333333"', gui_source)
        self.assertIn('"text": "#f0f0f0"', gui_source)
        self.assertIn("_style_chart_canvas", gui_source)

    def test_dark_log_colors(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        for tag in ('"error"', '"warning"', '"success"', '"info"'):
            self.assertIn(tag, gui_source)
        self.assertIn("tag_configure", gui_source)
        self.assertIn("_log_tag", gui_source)

    def test_v251_theme_mode_system_exists(self):
        from rephi_auto_chart.runtime import configured_theme_mode, detect_system_theme, effective_theme, save_configured_theme_mode

        original_localappdata = os.environ.get("LOCALAPPDATA")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "localappdata")
            try:
                layout, _ = ensure_runtime_layout()
                self.assertEqual(configured_theme_mode(layout), "system")
                self.assertIn(detect_system_theme(), {"light", "dark"})
                self.assertIn(effective_theme("system", layout), {"light", "dark"})
                save_configured_theme_mode("dark", layout)
                self.assertEqual(configured_theme_mode(layout), "dark")
            finally:
                if original_localappdata is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = original_localappdata

    def test_v251_windows_theme_detection_function(self):
        root = Path(__file__).resolve().parents[1]
        runtime_source = (root / "rephi_auto_chart" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn("def detect_windows_theme", runtime_source)
        self.assertIn("winreg", runtime_source)
        self.assertIn("AppsUseLightTheme", runtime_source)
        self.assertIn(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", runtime_source)

    def test_v251_theme_config_migration(self):
        from rephi_auto_chart.runtime import configured_theme_mode

        original_localappdata = os.environ.get("LOCALAPPDATA")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "localappdata")
            try:
                layout, _ = ensure_runtime_layout()
                data = read_runtime_config(layout)
                data.pop("theme_mode", None)
                data["theme"] = "dark"
                write_runtime_config(data, layout)
                self.assertEqual(configured_theme_mode(layout), "dark")
                migrated = read_runtime_config(layout)
                self.assertEqual(migrated.get("theme_mode"), "dark")
                self.assertNotIn("theme", migrated)
            finally:
                if original_localappdata is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = original_localappdata

    def test_v251_completion_dialog_uses_theme(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("def _show_completion_dialog", gui_source)
        self.assertIn("tk.Toplevel", gui_source)
        self.assertIn("dialog.configure(bg=palette", gui_source)
        self.assertIn("Open Folder", gui_source)
        self.assertIn("Continue Editing", gui_source)
        self.assertIn("Close", gui_source)
        self.assertIn("_style_dialog_button", gui_source)

    def test_v251_no_global_mousewheel_binding(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertNotIn('bind_all("<MouseWheel>"', gui_source)
        self.assertNotIn('bind_all("<Button-4>"', gui_source)
        self.assertNotIn('bind_all("<Button-5>"', gui_source)
        self.assertIn("def _bind_mousewheel", gui_source)
        self.assertIn("def _on_workspace_mousewheel", gui_source)
        self.assertIn("def _on_text_mousewheel", gui_source)

    def test_v251_stats_log_scroll_isolated(self):
        root = Path(__file__).resolve().parents[1]
        gui_source = (root / "rephi_auto_chart" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("self._bind_mousewheel(self.stats_text, self._on_text_mousewheel)", gui_source)
        self.assertIn("self._bind_mousewheel(self.log, self._on_text_mousewheel)", gui_source)
        self.assertIn('return "break"', gui_source)
        self.assertIn("event.widget.yview_scroll", gui_source)

    def test_version_251_consistency(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(rephi_auto_chart.__version__, "2.5.1")
        self.assertEqual((root / "VERSION").read_text(encoding="utf-8").strip(), "2.5.1")
        version_info = (root / "packaging" / "windows" / "version_info.txt").read_text(encoding="utf-8")
        installer = (root / "installer" / "inno_setup.iss").read_text(encoding="utf-8")
        release_check = (root / "release_check.ps1").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("ProductVersion', '2.5.1", version_info)
        self.assertIn('#define MyAppVersion "2.5.1"', installer)
        self.assertIn("2.5.1", release_check)
        self.assertIn("V2.5.1", readme)

    def test_chart_analyzer_writes_json_csv_html_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "clicks.wav"
            chart_path = root / "chart.json"
            reports = root / "reports"
            write_click_track(audio, bpm=120.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), "clicks.wav")
            export_rpe_chart(chart, chart_path)
            result = analyze_chart_file(chart_path)
            paths = write_analysis_reports(result, reports)
        self.assertGreater(result.total_notes, 0)
        self.assertGreaterEqual(result.tap_count, 1)
        self.assertTrue(paths["json"].name.endswith(".json"))
        self.assertTrue(paths["csv"].name.endswith(".csv"))
        self.assertTrue(paths["html"].name.endswith(".html"))

    def test_compare_and_batch_generate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio_a = root / "a.wav"
            audio_b = root / "b.wav"
            write_click_track(audio_a, bpm=120.0)
            write_click_track(audio_b, bpm=150.0)
            outputs = batch_generate([audio_a, audio_b], root / "batch", AssistantConfig(difficulty=Difficulty.HD), export_format="pez")
            comparison = compare_charts(outputs[0], outputs[1])
            report_paths = write_comparison_reports(comparison, root / "compare")
            self.assertEqual(len(outputs), 2)
            self.assertTrue(all(path.suffix == ".pez" for path in outputs))
            self.assertIn("total_notes", comparison.deltas)
            self.assertTrue(report_paths["json"].exists())
            self.assertTrue(report_paths["html"].exists())

    def test_startup_checks_are_human_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_startup_checks(Path(tmp))
        self.assertTrue(result.messages)
        self.assertTrue(all("Traceback" not in message for message in result.messages))

    def test_rephi_install_inspection_finds_embedded_example(self):
        install = Path("/Users/jiayihuang/Downloads/phigrosfanmadecharteditor")
        if not install.exists():
            self.skipTest("Re:PhiEdit install not present")
        report = inspect_rephi_install(install)
        self.assertTrue(report.example_charts)
        self.assertEqual(report.preferred_strategy, "external-tool-rpe-json")

    def test_no_tap_inside_hold(self):
        chart = {
            "BPMList": [{"bpm": 120.0, "startTime": [0, 0, 1]}],
            "META": {},
            "judgeLineGroup": ["Default"],
            "judgeLineList": [{"notes": [
                {"type": 2, "startTime": [0, 0, 1], "endTime": [4, 0, 1], "positionX": 0, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
                {"type": 1, "startTime": [2, 0, 1], "endTime": [2, 0, 1], "positionX": 20, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
            ], "eventLayers": [{"alphaEvents": [], "moveXEvents": [], "moveYEvents": [], "rotateEvents": [], "speedEvents": []}]}],
        }
        self.assertEqual(len(detect_notes_inside_holds(chart)), 1)
        fixed, report = validate_and_fix_chart(chart)
        self.assertEqual(detect_notes_inside_holds(fixed), [])
        self.assertGreaterEqual(report.notes_inside_hold_fixed_count, 1)

    def test_no_notes_inside_hold_region(self):
        chart = {
            "BPMList": [{"bpm": 120.0, "startTime": [0, 0, 1]}],
            "META": {},
            "judgeLineGroup": ["Default"],
            "judgeLineList": [{"notes": [
                {"type": 2, "startTime": [0, 0, 1], "endTime": [4, 0, 1], "positionX": -90, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
                {"type": 3, "startTime": [1, 0, 1], "endTime": [1, 0, 1], "positionX": -80, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
                {"type": 4, "startTime": [2, 0, 1], "endTime": [2, 0, 1], "positionX": -75, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
                {"type": 1, "startTime": [2, 0, 1], "endTime": [2, 0, 1], "positionX": 360, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
            ], "eventLayers": [{"alphaEvents": [], "moveXEvents": [], "moveYEvents": [], "rotateEvents": [], "speedEvents": []}]}],
        }
        fixed, report = validate_and_fix_chart(chart)
        self.assertEqual(detect_notes_inside_holds(fixed), [])
        self.assertGreaterEqual(report.notes_inside_hold_fixed_count, 2)
        far_notes = [note for note in fixed["judgeLineList"][0]["notes"] if note["positionX"] == 360]
        self.assertEqual(len(far_notes), 1)

    def test_at_hold_duration_limit(self):
        chart = {
            "BPMList": [{"bpm": 120.0, "startTime": [0, 0, 1]}],
            "META": {},
            "judgeLineGroup": ["Default"],
            "judgeLineList": [{"notes": [
                {"type": 2, "startTime": [0, 0, 1], "endTime": [12, 0, 1], "positionX": 0, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
            ], "eventLayers": [{"alphaEvents": [], "moveXEvents": [], "moveYEvents": [], "rotateEvents": [], "speedEvents": []}]}],
        }
        fixed, report = validate_and_fix_chart(chart, max_hold_duration_seconds=2.0)
        self.assertLessEqual(report.longest_hold_duration, 2.01)
        self.assertGreaterEqual(report.holds_trimmed_count, 1)
        hold = fixed["judgeLineList"][0]["notes"][0]
        self.assertLessEqual((beat_tuple_to_beats(hold["endTime"]) - beat_tuple_to_beats(hold["startTime"])) * 0.5, 2.01)

    def test_long_sustain_split_for_at(self):
        chart = {
            "BPMList": [{"bpm": 120.0, "startTime": [0, 0, 1]}],
            "META": {},
            "judgeLineGroup": ["Default"],
            "judgeLineList": [{"notes": [
                {"type": 2, "startTime": [0, 0, 1], "endTime": [10, 0, 1], "positionX": 0, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
                {"type": 1, "startTime": [3, 0, 1], "endTime": [3, 0, 1], "positionX": 0, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
                {"type": 3, "startTime": [6, 0, 1], "endTime": [6, 0, 1], "positionX": 0, "above": 1, "isFake": 0, "alpha": 255, "size": 1.0, "speed": 1.0, "visibleTime": 999999.0, "yOffset": 0.0},
            ], "eventLayers": [{"alphaEvents": [], "moveXEvents": [], "moveYEvents": [], "rotateEvents": [], "speedEvents": []}]}],
        }
        fixed, report = validate_and_fix_chart(chart, max_hold_duration_seconds=2.0)
        holds = [note for note in fixed["judgeLineList"][0]["notes"] if note["type"] == 2]
        self.assertTrue(holds)
        self.assertEqual(detect_notes_inside_holds(fixed), [])
        self.assertGreaterEqual(report.holds_split_count, 1)
        self.assertLessEqual(report.longest_hold_duration, 2.01)

    def test_at_not_hold_dominated(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "pattern.wav"
            write_pattern_song(audio, bpm=132.0, seconds=14.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), "pattern.wav")
        report = chart["META"]["autoChartReport"]
        self.assertLessEqual(report["hold_ratio"], 0.16)
        self.assertLessEqual(report["hold_timeline_coverage"], 0.24)
        self.assertGreaterEqual(report["type_ratios"]["tap"] + report["type_ratios"]["drag"], 0.55)

    def test_at_has_external_rhythm_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=168.0, seconds=14.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), "high_energy.wav")
        notes = chart["judgeLineList"][0]["notes"]
        self.assertEqual(detect_notes_inside_holds(chart), [])
        rhythm_notes = [note for note in notes if note["type"] in {1, 3, 4}]
        self.assertGreaterEqual(len(rhythm_notes), int(len(notes) * 0.75))

    def test_hold_does_not_suppress_density(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "pattern.wav"
            write_pattern_song(audio, bpm=150.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), "pattern.wav")
        report = chart["META"]["autoChartReport"]
        self.assertEqual(report["notes_inside_hold_fixed_count"], 0)
        self.assertGreater(report["tap_count"] + report["drag_count"] + report["flick_count"], report["hold_count"] * 4)
        self.assertGreater(report["note_count"], 80)

    def test_v240_pattern_generator_exposes_rule_based_library(self):
        names = set(pattern_library_names())
        required = {
            "Single",
            "Double",
            "Triple",
            "Quad",
            "Alternating",
            "Stair",
            "Jump",
            "Burst",
            "Stream",
            "Anchor",
            "Jack",
            "Trill",
            "Drag Chain",
            "Hold Anchor",
        }
        self.assertTrue(required.issubset(names))

    def test_v240_report_includes_pattern_layout_playability_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=168.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), audio.name)
        report = chart["META"]["autoChartReport"]
        for key in (
            "pattern_diversity_score",
            "layout_diversity_score",
            "playability_score",
            "average_jump_distance",
            "hand_alternation_score",
            "lane_distribution",
            "pattern_histogram",
            "longest_same_pattern",
            "longest_same_lane",
        ):
            self.assertIn(key, report)
        self.assertGreaterEqual(report["pattern_diversity_score"], 55.0)
        self.assertGreaterEqual(report["layout_diversity_score"], 55.0)
        self.assertGreaterEqual(report["playability_score"], 55.0)

    def test_v240_layout_avoids_long_same_lane_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "clicks.wav"
            write_click_track(audio, bpm=150.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), audio.name)
        notes = chart["judgeLineList"][0]["notes"]
        layout = compute_layout_report(notes)
        self.assertLessEqual(layout["longest_same_lane"], 4)
        self.assertGreaterEqual(layout["hand_alternation_score"], 45.0)
        self.assertGreater(len(layout["lane_distribution"]), 4)

    def test_v240_at_uses_more_pattern_complexity_than_hd(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "high_energy.wav"
            write_high_energy_track(audio, bpm=168.0, seconds=16.0)
            analysis = analyze_audio(audio)
            hd = generate_chart(analysis, AssistantConfig(difficulty=Difficulty.HD), audio.name)
            at = generate_chart(analysis, AssistantConfig(difficulty=Difficulty.AT), audio.name)
        hd_report = hd["META"]["autoChartReport"]
        at_report = at["META"]["autoChartReport"]
        self.assertGreaterEqual(at_report["pattern_diversity_score"], hd_report["pattern_diversity_score"])
        self.assertGreaterEqual(at_report["layout_diversity_score"], hd_report["layout_diversity_score"])
        self.assertGreater(at_report["pattern_complexity"], hd_report["pattern_complexity"])

    def test_v240_layout_validator_keeps_hold_conflicts_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "pattern.wav"
            write_pattern_song(audio, bpm=132.0, seconds=16.0)
            chart = generate_chart(analyze_audio(audio), AssistantConfig(difficulty=Difficulty.AT), audio.name)
        report = chart["META"]["autoChartReport"]
        self.assertEqual(detect_notes_inside_holds(chart), [])
        self.assertEqual(report["layout_validator_warnings"], [])
        self.assertEqual(report["pattern_validator_warnings"], [])


if __name__ == "__main__":
    unittest.main()
