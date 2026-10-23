import os
import sys
from pathlib import Path
import PyInstaller.__main__

# Ensure UTF-8 output even in environments with restrictive codepages (e.g. cp1252 in Windows CI)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent

def build():
    print("[Build] Starting Dictaphone application build...")
    icon_path = BASE_DIR / "resources" / "icon.ico"
    resources_path = BASE_DIR / "resources"

    args = [
        str(BASE_DIR / "main.py"),
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name=Dictaphone",
        f"--icon={icon_path}",
        f"--add-data={resources_path};resources",
        "--collect-all=sounddevice",
        "--collect-all=av",
        "--hidden-import=PyQt6",
        "--hidden-import=requests",
        "--hidden-import=session_validator",
    ]

    print("[Build] PyInstaller options:", " ".join(args))
    PyInstaller.__main__.run(args)
    print("\n[Build] Application build completed successfully! Executable: dist/Dictaphone/Dictaphone.exe")

if __name__ == "__main__":
    build()
