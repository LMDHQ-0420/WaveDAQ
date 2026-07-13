<p align="center">
  <img src="logo.png" width="120" alt="WaveDAQ Logo"/>
</p>

<h1 align="center">WaveDAQ</h1>

<p align="center">
  8-Channel UDP Real-Time Data Acquisition & Waveform Display
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-blue?logo=python" />
  <img src="https://img.shields.io/badge/PySide6-6.8.2-green?logo=qt" />
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey" />
  <img src="https://img.shields.io/github/v/release/LMDHQ-0420/WaveDAQ" />
</p>

<p align="center">
  <a href="README.md">中文</a> | <strong>English</strong>
</p>

---

## UI Preview

![WaveDAQ UI](UI.png)

---

## Features

- **Real-time acquisition**: Receives 8-channel waveform data over UDP (default port 8080) and renders it live
- **Record management**: Stores up to 20 acquisition records with view, re-acquire, and detail options
- **Threshold filtering**: Configurable amplitude upper/lower limits with live preview in a separate window — raw data is never modified
- **Inertial panning**: Main plot and filter plot support left-drag with momentum scrolling for smooth navigation
- **Linked zoom**: Main plot, filter plot, and overview are synchronized; the overview supports drag-to-seek
- **CSV export**: Select channels and export raw or filtered data; supports filename templates with date/time tokens
- **Appearance customization**: Per-channel color, background color, and per-channel visibility toggle

---

## Download

Go to [Releases](https://github.com/LMDHQ-0420/WaveDAQ/releases/latest) and download the package for your platform:

| Platform | File | Notes |
|----------|------|-------|
| macOS | `WaveDAQ-mac-vX.X.X.dmg` | Open the DMG and drag WaveDAQ.app to Applications. On first launch, right-click → **Open** to bypass Gatekeeper |
| Windows | `WaveDAQ-windows-vX.X.X.exe` | Double-click to run — no installation needed. If your antivirus flags it, choose "Allow" |

---

## Run from Source

**Requirements**: Python 3.11

```bash
# Clone the repo
git clone git@github.com:LMDHQ-0420/WaveDAQ.git
cd WaveDAQ

# Install dependencies (conda virtual environment recommended)
conda create -n WaveDAQ python=3.11 -y
conda activate WaveDAQ
pip install -r requirements.txt

# Launch
python run.py
```

---

## Data Format

Data is received on UDP port 8080 with the following frame structure:

```
| Header 4B   | Custom header 8B | Payload          | Footer 4B   |
| 5A5A5A5A   | 00...00          | 8ch × 128 pts    | 0D0A0D0A   |
```

- The payload is split into two halves, each containing 4 channels × 128 samples
- Each sample is a little-endian int16; normalization factor is 3276.8
- Use `test_udp_sender.py` to simulate sending test data

---

## Project Structure

```
WaveDAQ/
├── run.py                        # Entry point
├── requirements.txt
├── WaveDAQ.spec                  # PyInstaller build config
├── test_udp_sender.py            # UDP test data sender
├── .github/workflows/build.yml   # Automated build CI
└── core/
    ├── acquisition/
    │   ├── data_manager.py       # Acquisition state (pre-allocated buffers)
    │   ├── frame_parser.py       # UDP frame parser (vectorized)
    │   └── udp_receiver.py       # UDP receiver thread
    ├── signal/
    │   ├── filters.py            # Threshold filter (pure functions)
    │   └── downsampler.py        # Downsampler (pure functions)
    ├── export/
    │   └── csv_exporter.py       # CSV export and filename formatting
    └── ui/
        ├── main_window.py        # Main window (UI layout + event binding)
        ├── plot_controller.py    # Plot controller (viewport rendering + inertia)
        └── widgets.py            # Dialog components
```

---

## Local Build

```bash
# Install build tool
pip install pyinstaller

# macOS
pyinstaller WaveDAQ.spec
# Output: dist/WaveDAQ.app

# Windows
pyinstaller WaveDAQ.spec
# Output: dist/WaveDAQ.exe
```

---

## License

MIT
