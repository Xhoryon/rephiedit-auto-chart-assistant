# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]


EXCLUDED_MODULES = {
    "numpy.f2py.tests",
    "numpy.tests",
    "scipy.tests",
    "librosa.tests",
    "matplotlib.tests",
    "pytest",
    "test",
    "tests",
}


def is_excluded_module(name):
    return name in EXCLUDED_MODULES or any(
        name.startswith(prefix + ".") or f".{prefix}." in name
        for prefix in ("tests", "test")
    )


def optional_submodules(name):
    try:
        return collect_submodules(name, filter=lambda module_name: not is_excluded_module(module_name))
    except TypeError:
        try:
            return [module for module in collect_submodules(name) if not is_excluded_module(module)]
        except Exception:
            return []
    except Exception:
        return []


def optional_data_files(name):
    try:
        return [
            item
            for item in collect_data_files(name, excludes=["**/tests/**", "**/test/**"])
            if "\\tests\\" not in item[0].lower() and "/tests/" not in item[0].lower()
        ]
    except TypeError:
        try:
            return [
                item
                for item in collect_data_files(name)
                if "\\tests\\" not in item[0].lower()
                and "/tests/" not in item[0].lower()
                and "\\test\\" not in item[0].lower()
                and "/test/" not in item[0].lower()
            ]
        except Exception:
            return []
    except Exception:
        return []


def optional_dynamic_libs(name):
    try:
        return collect_dynamic_libs(name)
    except Exception:
        return []


hiddenimports = []
for package in (
    "tkinter",
    "PIL",
    "PIL._tkinter_finder",
    "soundfile",
    "librosa",
    "numpy",
    "scipy",
    "audioread",
    "matplotlib",
    "numba",
    "llvmlite",
    "soxr",
    "pooch",
    "joblib",
    "sklearn",
    "lazy_loader",
    "msgpack",
):
    hiddenimports += optional_submodules(package)

binaries = []
datas = [
    (str(ROOT / "config" / "default_config.json"), "config"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "CHANGELOG.md"), "."),
    (str(ROOT / "docs" / "FORMAT_ANALYSIS.md"), "docs"),
    (str(ROOT / "docs" / "ALGORITHM.md"), "docs"),
    (str(ROOT / "docs" / "TESTING.md"), "docs"),
    (str(ROOT / "docs" / "V2_SUMMARY.md"), "docs"),
    (str(ROOT / "docs" / "V3_PLAN.md"), "docs"),
    (str(ROOT / "docs" / "RELEASE_CHECKLIST.md"), "docs"),
    (str(ROOT / "docs" / "DEVELOPMENT_LOG.md"), "docs"),
    (str(ROOT / "assets" / "windows" / "app_icon.ico"), "assets/windows"),
]
ffmpeg_asset = ROOT / "assets" / "windows" / "ffmpeg.exe"
ffmpeg_license = ROOT / "assets" / "windows" / "FFMPEG_LICENSE.txt"
if ffmpeg_asset.exists():
    datas.append((str(ffmpeg_asset), "assets/windows"))
if ffmpeg_license.exists():
    datas.append((str(ffmpeg_license), "assets/windows"))

for package in ("soundfile", "librosa", "audioread", "PIL", "matplotlib", "numpy", "scipy"):
    datas += optional_data_files(package)

for package in ("numpy", "scipy", "soundfile", "llvmlite", "soxr"):
    binaries += optional_dynamic_libs(package)

hiddenimports = sorted({module for module in hiddenimports if not is_excluded_module(module)})

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "gui_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy.f2py.tests",
        "numpy.tests",
        "scipy.tests",
        "librosa.tests",
        "matplotlib.tests",
        "pytest",
        "test",
        "tests",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RePhiEditAutoChartAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "windows" / "app_icon.ico"),
    version=str(ROOT / "packaging" / "windows" / "version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="RePhiEditAutoChartAssistant",
)
