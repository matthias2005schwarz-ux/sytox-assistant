"""SYTOX desktop, background-autostart and non-destructive Qt startup tests."""
import sys


def main():
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == '--apply-update':
        # Minimal installer helper: wait for this app to exit before Inno starts.
        # Deliberately run without QApplication, agent, microphone or app mutex.
        from sytox.updater import run_update_helper
        return run_update_helper(args[1], args[2])
    valid = ([], ['--background'], ['--smoke-test'], ['--smoke-test', '--background'])
    if args not in valid:
        raise SystemExit('Unbekanntes Argument. Erlaubt: --background, --smoke-test.')
    smoke = '--smoke-test' in args
    background = '--background' in args

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from sytox.screen_ui import ScreenMainWindow as MainWindow

    app = QApplication([sys.argv[0]])
    app.setApplicationName('SYTOX Assistant')
    app.setQuitOnLastWindowClosed(False if QSystemTrayIcon.isSystemTrayAvailable() else True)

    bridge = None
    if not smoke:
        from sytox.instance import InstanceBridge
        from sytox.storage import default_data_dir
        bridge = InstanceBridge(default_data_dir())
        if not bridge.listen_or_signal(show=not background):
            return 0
        app.aboutToQuit.connect(bridge.close)

    window = MainWindow()
    if bridge:
        bridge.on_open = window.show_window
    if not background or not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()  # Never leave the user with an invisible app when tray is missing.
    if smoke:
        if window.chatlist is None or window.input is None or window.store is None:
            raise RuntimeError('SYTOX UI initialization incomplete')
        QTimer.singleShot(350, app.quit)
    return app.exec()


def run_with_startup_report():
    """Log fatal Qt/startup failures, including in --windowed PyInstaller EXEs."""
    try:
        return main()
    except Exception:
        import traceback
        message = traceback.format_exc()
        try:
            from sytox.storage import default_data_dir
            folder = default_data_dir()
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'startup_error.log').write_text(message, encoding='utf-8')
        except Exception:
            pass  # The original exception is still surfaced below.
        if sys.stderr is not None:
            sys.stderr.write(message)
        return 1


if __name__ == '__main__':
    raise SystemExit(run_with_startup_report())
