"""Build dist/TabLink (PyInstaller, onedir) with scrcpy bundled, then zip it."""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

from scrcpy_ctrl import SCRCPY_DIR  # noqa: E402
from ui import make_icon_image  # noqa: E402

os.makedirs("assets", exist_ok=True)
make_icon_image(256).save("assets/icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)])

subprocess.check_call([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
    "--name", "TabLink", "--icon", "assets/icon.ico",
    "--collect-all", "customtkinter", "--hidden-import", "pystray._win32",
    "app.py",
])

dist = os.path.join("dist", "TabLink")
shutil.copytree(SCRCPY_DIR, os.path.join(dist, "scrcpy"), dirs_exist_ok=True)
shutil.copy("README.md", dist)
shutil.copy("LICENSE", dist)
archive = shutil.make_archive(os.path.join("dist", "TabLink-win64"), "zip", "dist", "TabLink")
print("built", archive)
