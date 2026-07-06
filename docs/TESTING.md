# Testing

Run:

```sh
python3 -m unittest discover -s tests
```

Current tests:

- `test_audio_analysis_detects_click_track_bpm_and_onsets`
- `test_generate_chart_includes_all_supported_note_types_for_at`
- `test_validator_repairs_negative_time_and_hold_order`
- `test_export_and_reload_rpe_json`
- `test_export_rephi_package_includes_default_illustration`
- `test_rephi_install_inspection_finds_embedded_example`

The tests use a generated WAV click track, so they do not require external media or third-party Python packages.

Windows packaging scripts should be verified on Windows:

```powershell
.\scripts\build_windows_exe.ps1
.\scripts\build_windows_installer.ps1
```

These commands are not expected to produce a Windows installer from macOS.
