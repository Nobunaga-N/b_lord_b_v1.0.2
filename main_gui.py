"""
Точка входа в приложение Beast Lord Bot v3.0
"""

from gui.main_window import MainWindow


def main():
    """Запуск GUI приложения"""
    print("🚀 Beast Lord Bot v3.0")
    print("Запуск GUI...")

    # Создать главное окно
    app = MainWindow()

    # Запустить GUI (блокирующий вызов)
    app.mainloop()


if __name__ == "__main__":
    main()