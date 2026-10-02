#!/usr/bin/env python3
"""AI の作業が終わった（Stop）ときに、人へ通知音を鳴らす。
macOS は afplay、それ以外は端末のベル。通知が要らなければ .agents/hooks.json の "notify-when-done" を enabled: false に。"""
import platform
import subprocess
import sys

try:
    if platform.system() == "Darwin":
        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], timeout=5, check=False)
    else:
        sys.stdout.write("\a")
        sys.stdout.flush()
except Exception:
    pass
