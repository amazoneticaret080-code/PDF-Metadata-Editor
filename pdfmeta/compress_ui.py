"""PDF Küçült sekmesi: bir PDF ve hedef boyut (MB) verilir, hedefe sığan en kaliteli hali kaydedilir."""
from __future__ import annotations

import os
import subprocess
import sys
import traceback

import pikepdf
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import compress, theme
from .preview import PdfPreview
from .signing import signatures_in

OUTPUT_SUFFIX = "_kucultulmus"
MB = 1024 * 1024


def _unique_path(folder: str, filename: str) -> str:
    name, ext = os.path.splitext(filename)
    path = os.path.join(folder, filename)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{name} ({n}){ext}")
        n += 1
    return path


class _Worker(QObject):
    progress = Signal(str, int)
    finished = Signal(object)  # compress.Result
    failed = Signal(str, str)

    def __init__(self, src: str, dst: str, target: int, password: str):
        super().__init__()
        self.args = (src, dst, target, password)

    def run(self) -> None:
        src, dst, target, password = self.args
        try:
            result = compress.compress(src, dst, target, password, progress=self.progress.emit)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc) or exc.__class__.__name__, traceback.format_exc())
            return
        self.finished.emit(result)


class CompressPanel(QWidget):
    def __init__(self, output, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.output = output
        self.src = ""
        self.password = ""
        self.result_path = ""
        self._thread: QThread | None = None
        self._preview: PdfPreview | None = None

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignTop)

        # --- dosya ---
        file_box = QGroupBox("1. PDF Seçin")
        fl = QVBoxLayout(file_box)
        self.drop = QLabel("📄  PDF'i buraya sürükleyip bırakın veya aşağıdan seçin.")
        self.drop.setAlignment(Qt.AlignCenter)
        self.drop.setWordWrap(True)
        self._drop_style(False)
        fl.addWidget(self.drop)
        row = QHBoxLayout()
        b_choose = QPushButton("📂  PDF Seç…")
        self.b_view_src = QPushButton("👁  Görüntüle")
        self.b_view_src.setEnabled(False)
        row.addWidget(b_choose)
        row.addWidget(self.b_view_src)
        row.addStretch(1)
        fl.addLayout(row)
        root.addWidget(file_box)

        # --- hedef ---
        target_box = QGroupBox("2. Hedef Boyut")
        tl = QHBoxLayout(target_box)
        tl.addWidget(QLabel("En fazla:"))
        self.target = QDoubleSpinBox()
        self.target.setRange(0.01, 5000)
        self.target.setDecimals(2)
        self.target.setSingleStep(0.5)
        self.target.setValue(1.0)
        self.target.setSuffix(" MB")
        self.target.setMinimumWidth(130)
        tl.addWidget(self.target)
        self.target_hint = QLabel()
        self.target_hint.setStyleSheet(f"color:{theme.MUTED}; font-weight:400;")
        tl.addWidget(self.target_hint, 1)
        self.b_run = QPushButton("🗜  Küçült ve Kaydet")
        self.b_run.setProperty("primary", True)
        self.b_run.setMinimumHeight(36)
        self.b_run.setEnabled(False)
        tl.addWidget(self.b_run)
        root.addWidget(target_box)

        # --- sonuç ---
        res_box = QGroupBox("3. Sonuç")
        rl = QVBoxLayout(res_box)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(8)
        self.status = QLabel("Henüz küçültme yapılmadı.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        self.status.setStyleSheet("font-weight:400;")
        rl.addWidget(self.bar)
        rl.addWidget(self.status)
        row = QHBoxLayout()
        self.b_view_res = QPushButton("👁  Küçültülmüşü Görüntüle")
        self.b_show = QPushButton("📁  Klasörde Göster")
        for b in (self.b_view_res, self.b_show):
            b.setEnabled(False)
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(QLabel("Çıktı klasörü:"))
        self.out_label = QLabel()
        self.out_label.setStyleSheet(f"color:{theme.MUTED}; font-weight:400;")
        b_out = QPushButton("Değiştir…")
        row.addWidget(self.out_label)
        row.addWidget(b_out)
        rl.addLayout(row)
        root.addWidget(res_box)

        info = QLabel(
            "<b>Nasıl çalışır?</b> Önce kalite kaybı olmadan sıkıştırılır. Hedefe ulaşılamazsa resimler "
            "adım adım daha düşük kalite ve çözünürlükle yeniden kaydedilir ve <b>hedefe sığan en kaliteli</b> "
            "hali seçilir. Yazılar ve vektör çizimler bozulmaz; metadata (başlık, yazar, tarihler) aynen korunur. "
            "Resmi olmayan, yalnızca yazıdan oluşan PDF'ler çok fazla küçülmeyebilir. "
            "Dijital imzalı belgeler küçültülemez (imza bozulur)."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet(
            f"background:white; border:1px solid {theme.BORDER}; border-left:4px solid {theme.BLUE};"
            f" border-radius:8px; padding:10px; font-weight:400;"
        )
        root.addWidget(info)

        b_choose.clicked.connect(self._choose)
        self.b_view_src.clicked.connect(lambda: self._show_preview(self.src))
        self.b_view_res.clicked.connect(lambda: self._show_preview(self.result_path))
        self.b_show.clicked.connect(self._reveal)
        self.b_run.clicked.connect(self._run)
        self.target.valueChanged.connect(self._update_hint)
        b_out.clicked.connect(lambda: output.choose(self))
        output.changed.connect(self._show_output)
        self._show_output(output.path())

    # ------------------------------------------------------------------ #
    def _drop_style(self, loaded: bool) -> None:
        border = f"1px solid {theme.BORDER}; border-left:4px solid {theme.BLUE}" if loaded else \
            f"2px dashed {theme.BORDER}"
        self.drop.setStyleSheet(
            f"padding:16px; border:{border}; border-radius:8px; background:white;"
            f" color:{theme.TEXT if loaded else theme.MUTED}; font-weight:{600 if loaded else 400};"
        )

    def _show_output(self, path: str) -> None:
        self.out_label.setText(path if len(path) <= 50 else "…" + path[-49:])
        self.out_label.setToolTip(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(".pdf")]
        if paths:
            self.load(paths[0])

    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "PDF seç", "", "PDF dosyaları (*.pdf)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        password = ""
        while True:
            try:
                with pikepdf.open(path, password=password) as pdf:
                    pages = len(pdf.pages)
                    signed = signatures_in(pdf)
                break
            except pikepdf.PasswordError:
                pw, ok = QInputDialog.getText(
                    self, "Şifreli PDF", f"{os.path.basename(path)} şifreli.\nŞifreyi girin:", QLineEdit.Password
                )
                if not ok:
                    return
                password = pw
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "PDF açılamadı", str(exc))
                return
        self.src = os.path.normpath(path)
        self.password = password
        size = os.path.getsize(path)
        lock = "\n🔒 Bu belge dijital olarak imzalanmış; küçültülemez." if signed else ""
        self.drop.setText(f"📄  {os.path.basename(path)}\n{compress.human(size)} · {pages} sayfa{lock}")
        self.drop.setToolTip(self.src)
        self._drop_style(True)
        # varsayılan hedef: mevcut boyutun yarısı
        self.target.setValue(max(0.01, round(size / MB / 2, 2)))
        self.b_view_src.setEnabled(True)
        self.b_run.setEnabled(not signed)
        self.result_path = ""
        for b in (self.b_view_res, self.b_show):
            b.setEnabled(False)
        self.bar.setValue(0)
        self.status.setText("Hedef boyutu girip <b>Küçült ve Kaydet</b>'e basın.")
        self._update_hint()

    def _update_hint(self, *_) -> None:
        if not self.src:
            self.target_hint.setText("")
            return
        size = os.path.getsize(self.src)
        target = self.target.value() * MB
        if target >= size:
            self.target_hint.setText(f"Dosya zaten {compress.human(size)}; yalnızca kayıpsız sıkıştırma yapılır.")
        else:
            self.target_hint.setText(f"Şu an {compress.human(size)} → en fazla %{100 * target / size:.0f}'i")

    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        if not self.src or self._thread is not None:
            return
        if not os.path.exists(self.src):
            QMessageBox.warning(self, "PDF Küçült", "Kaynak dosya bulunamadı.")
            return
        try:
            folder = self.output.ensure()
        except OSError as exc:
            QMessageBox.critical(self, "Çıktı klasörü oluşturulamadı", str(exc))
            return
        name = os.path.splitext(os.path.basename(self.src))[0]
        if not name.endswith(OUTPUT_SUFFIX):
            name += OUTPUT_SUFFIX
        dst = _unique_path(folder, name + ".pdf")
        target = int(self.target.value() * MB)

        self.b_run.setEnabled(False)
        self.b_run.setText("⏳  Küçültülüyor…")
        self.bar.setValue(0)
        self._thread = QThread(self)
        self._worker = _Worker(self.src, dst, target, self.password)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        # lambda yerine metot: sonuç arayüz iş parçacığında işlensin
        self._job = (dst, target)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        for sig in (self._worker.finished, self._worker.failed):
            sig.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)
        self._thread.start()

    def _on_progress(self, text: str, pct: int) -> None:
        self.bar.setValue(pct)
        self.status.setText(text)

    def _cleanup(self) -> None:
        self._thread.deleteLater()
        self._worker.deleteLater()
        self._thread = None
        self.b_run.setText("🗜  Küçült ve Kaydet")
        self.b_run.setEnabled(bool(self.src))

    def _on_finished(self, result: compress.Result) -> None:
        dst, target = self._job
        before = os.path.getsize(self.src)
        pct = 100 * (1 - result.size / before) if before else 0
        self.result_path = dst
        for b in (self.b_view_res, self.b_show):
            b.setEnabled(True)
        self.bar.setValue(100)
        line = (
            f"<b>{compress.human(before)} → {compress.human(result.size)}</b> "
            f"({'%' + format(pct, '.0f') + ' daha küçük' if pct > 0 else 'küçülmedi'}) · Yöntem: {result.level}"
            f"<br>Kaydedildi: {dst}"
        )
        if result.reached:
            self.status.setText(f"<span style='color:#1b873f'>✔ Hedefe ulaşıldı.</span> {line}")
        else:
            self.status.setText(
                f"<span style='color:#c77700'>⚠ {compress.human(target)} hedefine ulaşılamadı; "
                f"elde edilebilen en küçük hali kaydedildi.</span> {line}"
            )
        self.window().statusBar().showMessage(f"Küçültüldü: {dst}", 10000)

    def _on_failed(self, message: str, details: str) -> None:
        self.bar.setValue(0)
        self.status.setText(f"<span style='color:#b3261e'>✖ Küçültülemedi: {message}</span>")
        box = QMessageBox(QMessageBox.Critical, "Küçültülemedi", message, parent=self)
        box.setDetailedText(details)
        box.exec()

    def _show_preview(self, path: str) -> None:
        if not path:
            return
        if self._preview is None:
            self._preview = PdfPreview(self.window())
        self._preview.set_nav_enabled(False, False)
        self._preview.show_file(path, self.password)
        self._preview.show()
        self._preview.raise_()
        self._preview.activateWindow()

    def _reveal(self) -> None:
        if self.result_path and sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.result_path)])
