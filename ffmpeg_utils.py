"""
FFmpeg / ffprobe binary discovery.

Priority order:
  1. Bundled binary: <app_root>/bin/ffmpeg[.exe]
  2. System PATH

Place a static ffmpeg binary inside the bin/ folder to have it bundled
automatically by PyInstaller (add the folder to datas in your .spec file).
The bin/ folder ships empty — drop the binary in before packaging.
System ffmpeg is used as a fallback while developing without a bundled binary.

ffprobe is optional; the CI build intentionally omits it to keep the
bundle size down.  pydub falls back gracefully when ffprobe is absent.
"""

import shutil
import sys
from pathlib import Path


def _app_root() -> Path:
    """
    Return the root directory for binary lookup.

    - PyInstaller onefile  → sys._MEIPASS  (extraction temp dir)
    - PyInstaller onefolder → directory containing sys.executable
    - Plain script         → directory containing this file
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).parent
    return Path(__file__).parent


def find_binary(name: str) -> str | None:
    """
    Locate *name* ('ffmpeg' or 'ffprobe').

    Returns the absolute path string, or None if neither bundled nor on PATH.
    """
    exe = name + (".exe" if sys.platform == "win32" else "")

    bundled = _app_root() / "bin" / exe
    if bundled.is_file():
        return str(bundled)

    return shutil.which(name)


def configure_pydub() -> tuple[str | None, str | None]:
    """
    Point pydub at the best available ffmpeg / ffprobe binaries.

    Call once at application startup before any AudioSegment operations.
    Returns (ffmpeg_path, ffprobe_path); either may be None if not found.
    Raises RuntimeError if ffmpeg cannot be located at all.
    """
    from pydub import AudioSegment

    ffmpeg = find_binary("ffmpeg")
    ffprobe = find_binary("ffprobe")

    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg not found.\n\n"
            "Either place an ffmpeg binary in the bin/ folder next to this "
            "app, or install ffmpeg system-wide so it is on your PATH."
        )

    AudioSegment.converter = ffmpeg
    if ffprobe:
        AudioSegment.ffprobe = ffprobe

    return ffmpeg, ffprobe
