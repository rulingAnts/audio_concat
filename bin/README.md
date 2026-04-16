# bin/ — bundled ffmpeg binary

Place a platform-specific static ffmpeg binary here so it is found by
`ffmpeg_utils.py` at runtime and bundled by PyInstaller.

Expected filenames:

| Platform | Required      | Optional        |
|----------|---------------|-----------------|
| macOS    | `ffmpeg`      | `ffprobe`       |
| Linux    | `ffmpeg`      | `ffprobe`       |
| Windows  | `ffmpeg.exe`  | `ffprobe.exe`   |

ffprobe is optional — pydub falls back gracefully without it. The CI
build omits it to keep the bundle size down (~70 MB savings on macOS).

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
