"""Точка входа Get-Git."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.core import git_ops
from app.logging_setup import setup_logging
from app.ui.main_window import MainWindow


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Get-Git")

    if not git_ops.find_git():
        QMessageBox.critical(
            None,
            "Git не найден",
            "Не найден git в PATH.\n\n"
            "Установите Git for Windows (https://git-scm.com/download/win) "
            "и запустите приложение снова.",
        )
        return 1

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
