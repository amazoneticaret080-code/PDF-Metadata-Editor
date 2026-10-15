import os
import sys
import traceback


def _log_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PDFMetadataDuzenleyici", "hata_kaydi.log")


def _setup_logging() -> None:
    """Pencereli exe'de (konsol yok) sys.stdout/stderr None olur; bir yere yazılmaya çalışılması
    programı sessizce kapatabilir. Çıktıyı bir günlük dosyasına yönlendirir."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        os.makedirs(os.path.dirname(_log_path()), exist_ok=True)
        log = open(_log_path(), "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - program boyunca açık
    except OSError:
        log = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log

    def hook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb, file=sys.stderr)

    sys.excepthook = hook


_setup_logging()

from PySide6.QtWidgets import QApplication  # noqa: E402

from pdfmeta.theme import apply_theme  # noqa: E402
from pdfmeta.ui import APP_NAME, MainWindow  # noqa: E402


def main() -> int:
    if sys.platform == "win32":
        # görev çubuğunda Python yerine uygulamanın kendi ikonu görünsün
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SuspendGlobal.PDFMetadataDuzenleyici")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_theme(app)
    win = MainWindow()
    win.show()
    # komut satırından ya da .exe üzerine sürüklenerek verilen PDF'i aç
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".pdf"):
        win.single.load(sys.argv[1])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
