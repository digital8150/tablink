"""TabLink: play Android tablet audio on the PC and use the tablet as an extra 'monitor' for mouse/keyboard."""
import ctypes
import sys

import winio

winio.set_dpi_aware()

from core import APP_NAME  # noqa: E402
from ui import App  # noqa: E402


def main():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "TabLink_single_instance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(None, "TabLink가 이미 실행 중입니다 (트레이 확인).", APP_NAME, 0x40)
        return
    App(start_hidden="--tray" in sys.argv).run()
    del mutex


if __name__ == "__main__":
    main()
