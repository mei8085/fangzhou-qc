"""T4705S 专用：豆瓣监控守护脚本类题目的复测截图。

对每个模型：
1. Popen 起 douban_monitor.py（-u 无缓冲），采集约 10s stdout，然后 terminate。
   得到 boot banner + 特性开关状态 + 首次巡检 → 01_smoke.png
2. 静态扫描 douban_monitor.py 中六项需求的关键 pattern → 02_features.png
3. 横向拼合 → <COL>_verify.png

只放在 tasks/T4705S 复测使用；如以后再有类似长循环 python 脚本再复用。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose_cli import (
    _FONT_CANDIDATES,
    _LABEL_FONT_CANDIDATES,
    load_font,
    render_panel,
    trim_panel,
)
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

_CJK_MONO = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    *_FONT_CANDIDATES,
]

SMOKE_SECS = 10


def run_smoke(model_dir: Path) -> str:
    """Popen 起脚本，采 SMOKE_SECS 秒 stdout+stderr 合并流。"""
    p = subprocess.Popen(
        [sys.executable, "-u", "douban_monitor.py"],
        cwd=str(model_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    buf: list[str] = []

    def reader():
        try:
            for line in p.stdout:
                buf.append(line)
        except Exception:
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    time.sleep(SMOKE_SECS)
    try:
        p.terminate()
        p.wait(timeout=3)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    t.join(timeout=1)
    return f"$ python -u douban_monitor.py  (采集 {SMOKE_SECS}s)\n\n" + "".join(buf).strip()


def check_features(src: str) -> str:
    """按需求条目静态扫描，输出勾表。"""
    lines: list[str] = []
    def add(ok: bool, label: str) -> None:
        mark = "[OK]" if ok else "[NG]"
        lines.append(f"{mark}  {label}")

    add("from plyer import notification" not in src and "desktop_notify" not in src.split("def process_new_posts")[0].split("def show_custom_dialog")[0],
        "R1a 移除 plyer 依赖与 desktop_notify 定义")
    add("import tkinter" in src or "tkinter as tk" in src, "R1b 引入 tkinter")
    add("def show_custom_dialog" in src, "R1c show_custom_dialog 已定义")
    add("Toplevel" in src or "tk.Tk()" in src, "R1d tkinter 模态窗口")
    add("webbrowser.open" in src, "R1e 「打开帖子」调 webbrowser.open")
    add("clipboard_append" in src, "R1f 「复制链接」写剪贴板")
    has_60s = any(k in src for k in ("60000", "60 * 1000", "* 60000", "remaining = [60]", "* 60 * 1000"))
    add(has_60s, "R1g 60 秒无操作自动关闭")
    add("threading.Thread" in src and "show_custom_dialog" in src, "R1h 独立线程运行不阻塞")
    dedup = any(k in src for k in ("_shown", "_dialog_shown", "dialog_shown_urls", "_dialog_shown"))
    add(dedup, "R1i 同一帖子只弹一次（去重集合）")

    add("def play_sound_by_type" in src, "R2a play_sound_by_type 已定义")
    add("winsound.Beep(1000, 500)" in src, "R2b 红贴 1000Hz 500ms")
    add("winsound.Beep(1500, 500)" in src, "R2c 待判断 1500Hz 500ms x2")
    add("winsound.Beep(2000, 500)" in src, "R2d 黑贴 2000Hz 500ms x2")
    add("enable_sound" in src or "ENABLE_SOUND" in src, "R2e 受 enable_sound 配置控制")
    add("HAS_WINSOUND" in src or "WINSOUND_AVAILABLE" in src, "R2f 非 Windows 静默跳过")

    add("import pystray" in src, "R3a 引入 pystray")
    add("from PIL import" in src, "R3b 引入 PIL")
    add('豆' in src or 'text = "豆"' in src or "'豆'" in src, "R3c 图标含「豆」字")
    add("pystray.Icon" in src, "R3d pystray.Icon 已创建")
    add("状态" in src and "打开配置" in src and "退出" in src, "R3e 菜单三项完备")
    add("config_editor" in src, "R3f 「打开配置」调 config_editor")
    add("os._exit" in src or "_running" in src or "_tray_stop_event" in src, "R3g 「退出」结束监控")
    add("HAS_TRAY" in src or "TRAY_AVAILABLE" in src, "R3h 缺依赖降级不崩")

    add("status.json" in src, "R4a 状态文件写入 status.json")
    add("update_status_file" in src, "R4b update_status_file 已定义")
    add("total" in src.lower() and ("red" in src.lower() or "红" in src) and ("black" in src.lower() or "黑" in src), "R4c 累计统计字段完整")
    add("[:20]" in src or "20]" in src, "R4d 最多保留 20 条")
    add("last_check_time" in src or "check_time" in src, "R4e 记录上次检查时间")

    add("update_status_file" in src.split("def process_new_posts")[1] if "def process_new_posts" in src else False,
        "R5a process_new_posts 调 update_status_file")
    add("play_sound_by_type" in src.split("def process_new_posts")[1] if "def process_new_posts" in src else False,
        "R5b process_new_posts 调 play_sound_by_type")
    add("show_custom_dialog" in src.split("def process_new_posts")[1] if "def process_new_posts" in src else False,
        "R5c process_new_posts 调 show_custom_dialog")
    add("desktop_notify" not in src.split("def process_new_posts")[1] if "def process_new_posts" in src else False,
        "R5d process_new_posts 不再调 desktop_notify")

    add("except ImportError" in src or "try:\n    import tkinter" in src or "try:\n    import winsound" in src,
        "R6a 顶部 import 用 try/except 兜底")
    add(("HAS_TRAY" in src or "TRAY_AVAILABLE" in src) and ("if not HAS_TRAY" in src or "if not TRAY_AVAILABLE" in src or "return None" in src),
        "R6b 缺 pystray/Pillow 静默降级")

    return "静态需求核对（R1 弹窗 · R2 声音 · R3 托盘 · R4 状态 · R5 process · R6 依赖降级）\n\n" + "\n".join(lines)


def main() -> int:
    task_id = sys.argv[1] if len(sys.argv) > 1 else "T4705S"
    task_dir = REPO_ROOT / "tasks" / task_id
    mm_path = task_dir / "model_map.json"
    if not mm_path.exists():
        print(f"ERROR: {mm_path} not found", file=sys.stderr)
        return 2
    mm = json.loads(mm_path.read_text(encoding="utf-8"))
    out_dir = REPO_ROOT / "delivery" / task_id / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    mono = load_font(_CJK_MONO, 13)
    panel_w, panel_h = 900, 1400

    for col, info in mm["models"].items():
        code = info["code"]
        model_dir = task_dir / "extracted" / code
        print(f"==> {col} ({code})")

        tag = col.replace(" ", "_")

        # panel 1: 冷启动 smoke
        smoke_text = run_smoke(model_dir)
        p1 = trim_panel(render_panel(smoke_text, mono, (panel_w, panel_h)))
        p1_path = out_dir / f"{tag}_01_smoke.png"
        p1.save(p1_path)
        print(f"   -> {p1_path.name}  ({p1.height}px)")

        # panel 2: 需求核对
        src = (model_dir / "douban_monitor.py").read_text(encoding="utf-8", errors="replace")
        feat_text = check_features(src)
        p2 = trim_panel(render_panel(feat_text, mono, (panel_w, panel_h)))
        p2_path = out_dir / f"{tag}_02_features.png"
        p2.save(p2_path)
        print(f"   -> {p2_path.name}  ({p2.height}px)")

        # 拼合
        gap = 8
        total_w = p1.width + p2.width + gap * 3
        total_h = max(p1.height, p2.height) + gap * 2
        canvas = Image.new("RGB", (total_w, total_h), "black")
        canvas.paste(p1, (gap, gap))
        canvas.paste(p2, (gap * 2 + p1.width, gap))
        v_path = out_dir / f"{tag}_verify.png"
        canvas.save(v_path)
        print(f"   -> {v_path.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
