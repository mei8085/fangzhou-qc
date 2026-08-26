"""Cross-platform font candidates for evidence PNG rendering."""

from __future__ import annotations

import glob
from pathlib import Path

from PIL import ImageFont

MONO_FONT_CANDIDATES = [
    # macOS Terminal.app Basic profile uses SFMonoTerminal-Regular. Pillow
    # cannot open that private font by family name, but this is the bundled
    # SF mono face exposed on disk and is the closest available renderer.
    "/System/Library/Fonts/SFNSMono.ttf",
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    r"C:\Windows\Fonts\CascadiaMono.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Menlo.ttc",
    "/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
]

CJK_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    # Terminal.app stores only the primary mono font; macOS resolves Chinese
    # through CoreText fallback. Use the local system CJK faces in that order.
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font*/**/PingFang.ttc#3",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]

# Mixed CJK prose (static walkthrough notes) may use CJK faces.
# CLI / test / terminal evidence MUST use MONO_FONT_CANDIDATES. Proportional
# CJK faces (Hiragino, PingFang) make digit 4 lose its crossbar.
FONT_CANDIDATES = [*CJK_FONT_CANDIDATES, *MONO_FONT_CANDIDATES]


def load_font(candidates, size):
    """Load the first usable TrueType/TTC font, else Pillow's default bitmap font."""
    for p in candidates:
        font_index = 0
        pattern = p
        if "#" in p:
            pattern, raw_index = p.rsplit("#", 1)
            try:
                font_index = int(raw_index)
            except ValueError:
                font_index = 0
        paths = sorted(glob.glob(pattern, recursive=True)) if any(ch in pattern for ch in "*?[") else [pattern]
        for candidate in paths:
            if not Path(candidate).exists():
                continue
            try:
                return ImageFont.truetype(candidate, size, index=font_index)
            except OSError:
                continue
    return ImageFont.load_default()
