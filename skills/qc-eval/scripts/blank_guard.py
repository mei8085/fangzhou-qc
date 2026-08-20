#!/usr/bin/env python3
"""扫 delivery/<TASK_ID>/screenshots/ 下的截图，判三类不合格：

1. 空白帧：>=99% 像素与主色一致（跑不通就把白屏截出来当证据是没用的）
2. 冗余帧：同一 <COL> 下相邻两张 byte 一致（自动截图选择器没匹配到，等 N 秒
   截了一张一模一样的），说明这一步没截到新东西
3. 人工抬头：截图顶部额外拼了标题/说明横幅。证据图应直接呈现页面、终端、
   接口或报错本身，不要加"Task xxx verification evidence"这类抬头。
4. 目录杂物：screenshots 目录只允许有效截图 PNG 和 *_verify.png 合成图，
   不允许保留 log.txt、临时图、别名图或其他辅助文件。

规则：一张截图必须承载可读信息。跑不通的场景要换成报错终端、浏览器 console
错误或出错源码文件的截图；跑得通但截不出变化的场景，删掉这张而不是让它跟前
一张长得完全一样。

嵌入位置：run.py emit 阶段 compose 之后、push_xlsx 之前调用；push_feishu.py
在真写前也调一次。命中即视为不合格，需要手动补截图后重跑。

用法：
    blank_guard.py <TASK_ID> [<TASK_ID> ...] [--threshold 0.99]

退出码：0=干净；1=有 blank / duplicate / header 命中。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

# 单图内主色像素占比 >= THRESHOLD 判定为纯色/空白。
DEFAULT_THRESHOLD = 0.99
# 采样步长：像素太多没必要逐点扫；每 4 像素采一次，误差可以接受。
SAMPLE_STEP = 4

# 只针对个人截图（<COL>_NN_*.png），不看 <COL>_verify.png 合成图。
INDIVIDUAL_RE = re.compile(r"^.+?_\d+_.+\.png$")
VERIFY_RE = re.compile(r"^.+?_verify\.png$")

# 抬头检测只拦截"顶部一整条纯色标题栏 + 下方主体色明显不同"的人工证据卡片。
# 终端截图顶部和主体通常同色，不会命中；普通页面内局部标题栏也很难满足整条
# 顶部高占比纯色 + 与下方强反差这两个条件。
HEADER_MIN_HEIGHT = 56
HEADER_MAX_HEIGHT = 120
HEADER_MAX_IMAGE_RATIO = 0.18
HEADER_DOMINANT_RATIO = 0.72
HEADER_BODY_DOMINANT_RATIO = 0.50
HEADER_COLOR_DISTANCE = 80


def dominant_ratio(img: Image.Image) -> tuple[tuple[int, int, int], float]:
    img = img.convert("RGB")
    w, h = img.size
    px = img.load()
    counter: Counter[tuple[int, int, int]] = Counter()
    total = 0
    for y in range(0, h, SAMPLE_STEP):
        for x in range(0, w, SAMPLE_STEP):
            counter[px[x, y]] += 1
            total += 1
    if total == 0:
        return (0, 0, 0), 1.0
    color, count = counter.most_common(1)[0]
    return color, count / total


def region_dominant_ratio(img: Image.Image, box: tuple[int, int, int, int]) -> tuple[tuple[int, int, int], float]:
    """Return dominant RGB color and ratio for a rectangular region."""
    img = img.convert("RGB")
    left, top, right, bottom = box
    px = img.load()
    counter: Counter[tuple[int, int, int]] = Counter()
    total = 0
    for y in range(top, bottom, SAMPLE_STEP):
        for x in range(left, right, SAMPLE_STEP):
            counter[px[x, y]] += 1
            total += 1
    if total == 0:
        return (0, 0, 0), 1.0
    color, count = counter.most_common(1)[0]
    return color, count / total


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def has_artificial_header(img: Image.Image) -> bool:
    """Detect screenshots with an added title/header band at the very top."""
    w, h = img.size
    if w < 300 or h < 220:
        return False
    header_h = min(HEADER_MAX_HEIGHT, max(HEADER_MIN_HEIGHT, int(h * 0.14)))
    if header_h / h > HEADER_MAX_IMAGE_RATIO:
        return False
    top_color, top_ratio = region_dominant_ratio(img, (0, 0, w, header_h))
    # Sample the body immediately below the suspected header, not the whole image,
    # so long white unused areas do not dominate the decision.
    body_bottom = min(h, header_h * 3)
    body_color, body_ratio = region_dominant_ratio(img, (0, header_h, w, body_bottom))
    return (
        top_ratio >= HEADER_DOMINANT_RATIO
        and body_ratio >= HEADER_BODY_DOMINANT_RATIO
        and color_distance(top_color, body_color) >= HEADER_COLOR_DISTANCE
    )


_FRAME_PREFIX_RE = re.compile(r"^(.+?)_\d+_.+\.png$")


def scan_task(task_id: str, threshold: float) -> list[str]:
    out_dir = REPO_ROOT / "delivery" / task_id / "screenshots"
    if not out_dir.exists():
        return [f"missing dir: {out_dir}"]
    bad: list[str] = []
    for p in sorted(x for x in out_dir.iterdir() if x.is_file()):
        if p.suffix.lower() != ".png":
            bad.append(f"{p.name}: screenshots dir only allows PNG evidence/composite images")
        elif not (INDIVIDUAL_RE.match(p.name) or VERIFY_RE.match(p.name)):
            bad.append(f"{p.name}: PNG name must be an evidence frame *_NN_*.png or composite *_verify.png")
    pngs = sorted(out_dir.glob("*.png"))
    for p in pngs:
        try:
            with Image.open(p) as im:
                if has_artificial_header(im):
                    bad.append(f"{p.name}: artificial title/header band at top; crop the heading and keep only evidence")
        except Exception as e:  # noqa: BLE001
            bad.append(f"{p.name}: unreadable ({e})")

    frames = [p for p in pngs if INDIVIDUAL_RE.match(p.name)]
    if not frames:
        bad.append(f"no individual PNG frames under {out_dir}")
        return bad
    # 分组到 <COL>，逐组按文件名排序后比较相邻 byte hash
    prev_by_col: dict[str, tuple[str, str]] = {}  # col -> (prev name, prev sha1)
    for p in frames:
        try:
            with Image.open(p) as im:
                color, ratio = dominant_ratio(im)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{p.name}: unreadable ({e})")
            continue
        if ratio >= threshold:
            hexcolor = "#" + "".join(f"{c:02X}" for c in color)
            bad.append(f"{p.name}: {ratio:.1%} pixels are {hexcolor} (looks blank)")
            continue
        # byte-hash 用于查同 <COL> 下的重复相邻帧
        m = _FRAME_PREFIX_RE.match(p.name)
        if not m:
            continue
        col = m.group(1)
        sha = hashlib.sha1(p.read_bytes()).hexdigest()
        prev = prev_by_col.get(col)
        if prev and prev[1] == sha:
            bad.append(f"{p.name}: byte-identical to {prev[0]} (screenshot step captured no change)")
        prev_by_col[col] = (p.name, sha)
    return bad


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task_ids", nargs="+")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help=f"dominant-color ratio to flag (default {DEFAULT_THRESHOLD})")
    args = p.parse_args()
    total_bad = 0
    for tid in args.task_ids:
        bad = scan_task(tid, args.threshold)
        if bad:
            print(f"  [BAD] {tid}")
            for issue in bad:
                print(f"     {issue}")
            total_bad += 1
        else:
            print(f"  [OK]  {tid}")
    if total_bad:
        print(
            "\n空白截图、与前一张 byte 一致的截图、或带人工抬头/标题横幅的截图都不是"
            "合格证据。跑不通的场景请换成报错终端、浏览器 console 错误或出错源码文件"
            "的截图；跑得通但截不出变化的场景请删掉那张，证据图不要额外拼接说明抬头。",
            file=sys.stderr,
        )
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
