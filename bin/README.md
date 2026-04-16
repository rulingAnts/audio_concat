# bin/ — bundled ffmpeg binaries

Place platform-specific static ffmpeg and ffprobe binaries here so they
are found by `ffmpeg_utils.py` at runtime and bundled by PyInstaller.

Expected filenames:

| Platform | Files               |
|----------|---------------------|
| macOS    | `ffmpeg`, `ffprobe` |
| Linux    | `ffmpeg`, `ffprobe` |
| Windows  | `ffmpeg.exe`, `ffprobe.exe` |

The app falls back to the system-wide `ffmpeg`/`ffprobe` (PATH) when no
bundled binary is present, which is convenient during development.

## Where to get static builds

- **macOS / Linux**: <https://www.ffmpeg.org/download.html> → "Static Builds"
  or via `brew install ffmpeg` then copy the binaries.
- **Windows**: <https://www.gyan.dev/ffmpeg/builds/> (ffmpeg-release-essentials)

## PyInstaller .spec snippet

```python
datas=[
    ("bin/ffmpeg",  "bin"),   # macOS/Linux
    ("bin/ffprobe", "bin"),
    # ("bin/ffmpeg.exe",  "bin"),  # Windows
    # ("bin/ffprobe.exe", "bin"),
],
```
