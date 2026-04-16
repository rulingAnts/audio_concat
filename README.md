# Audio Concatenator

A cross-platform desktop app for loading a folder of audio files, arranging
them in any order, and joining them into a single WAV file with a short click
sound between each file — useful for creating stimulus lists, demos, and
audio databases.

**[Full documentation →](https://sethj.github.io/concat/)**

---

## Features

- Load a folder of audio files (WAV, MP3, FLAC, AIFF, OGG, M4A)
- Drag-and-drop reordering with multi-select (Shift+Click, Ctrl/Cmd+Click)
- **Simple sort mode** — sort by name, numerical order, date created/modified/accessed
- **Suffix Order** — sub-sort files that share a base name by an ordered list of
  substring/regex patterns (designed for [Dekereke](https://dekereke.com) databases
  where each stimulus has multiple tagged variants)
- **Advanced (Regex) sort mode** — multi-layer regex sort with configurable capture
  groups, sort-as modes (natural text, numeric, alphabetical), and per-layer direction
- Output bit depth: 16-bit (default), 24-bit, or 32-bit WAV
- Non-blocking join (runs on a background thread)
- Works as a plain Python script or as a PyInstaller portable app (Windows, macOS, Linux)

---

## Requirements

- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/)
- [pydub](https://pypi.org/project/pydub/)
- [numpy](https://pypi.org/project/numpy/)
- [ffmpeg](https://ffmpeg.org/) — system-wide install, or drop a static binary into
  `bin/ffmpeg` (see [`bin/README.md`](bin/README.md))

```
pip install PySide6 pydub numpy
```

---

## Running

```bash
python app.py
```

---

## Building a portable app (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --onefile app.py
```

Place `ffmpeg` (and optionally `ffprobe`) binaries inside `bin/` before
packaging so they are bundled automatically. See [`bin/README.md`](bin/README.md)
for the `.spec` snippet and where to download static builds.

---

## Project structure

```
app.py            Main GUI (PySide6)
joiner.py         Audio join worker (pydub, numpy)
ffmpeg_utils.py   ffmpeg/ffprobe binary discovery
bin/              Placeholder for bundled ffmpeg binaries
docs/             GitHub Pages documentation site
```

---

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE).  
Copyright 2026 Seth Johnston.

Built with assistance from [Claude](https://claude.ai) by Anthropic.
