import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config import APP_DIR
from app.main_window import MainWindow
from app.single_instance import SingleInstanceGuard

ICON_PATH = APP_DIR / "resources" / "icon.png"


def main() -> int:
    app = QApplication(sys.argv)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    guard = SingleInstanceGuard()
    if not guard.try_acquire():
        # Another instance is already running and has just been asked to
        # raise its window - nothing more to do here.
        return 0

    window = MainWindow()

    def _raise_window() -> None:
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        window.activateWindow()

    guard.activation_requested.connect(_raise_window)

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
