"""Точка входа Get-Git."""
from __future__ import annotations

import ctypes
import logging
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core import git_ops
from app.logging_setup import setup_logging
from app.resources import resource_path
from app.ui.main_window import MainWindow


def main() -> int:
    setup_logging()
    if sys.platform == "win32":
        # Собственный AppUserModelID: иначе при запуске из python.exe панель задач
        # группирует окно под иконкой Python
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GetGit.App")
    app = QApplication(sys.argv)
    app.setApplicationName("Get-Git")
    icon_file = resource_path("assets/get-git.ico")
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))

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
    exit_code = app.exec()

    # Страховка от зависшего в процессах приложения: если фоновые потоки
    # не завершились за отведённое время — завершаем процесс принудительно
    if not window.shutdown():
        logging.getLogger(__name__).warning(
            "Фоновые задачи не завершились за 5 с — принудительный выход"
        )
        os._exit(exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
