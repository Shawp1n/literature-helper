from __future__ import annotations

import platform
import shutil
import subprocess


def notify(title: str, message: str) -> bool:
    """Best-effort local notification. Notification failures never fail a task."""
    system = platform.system()
    try:
        if system == "Darwin" and shutil.which("osascript"):
            script = (
                "on run argv\n"
                "display notification (item 2 of argv) with title (item 1 of argv)\n"
                "end run"
            )
            subprocess.run(
                ["osascript", "-e", script, "--", title, message],
                check=True,
                timeout=10,
                capture_output=True,
                text=True,
            )
            return True
        if system == "Linux" and shutil.which("notify-send"):
            subprocess.run(
                ["notify-send", title, message],
                check=True,
                timeout=10,
                capture_output=True,
                text=True,
            )
            return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False
