"""Uygulama içi hızlı PDF önizleme penceresi (QtPdf)."""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import theme

ZOOM_STEP = 1.25


class PdfPreview(QDialog):
    """Tek pencere; listede başka dosyaya geçildiğinde içeriği değişir.

    navigate(adım) -> None: önceki/sonraki dosyaya geçmek için çağıranın verdiği fonksiyon.
    """

    def __init__(self, parent=None, navigate=None):
        super().__init__(parent)
        self.setWindowTitle("PDF Önizleme")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(900, 1000)
        self._navigate = navigate
        self.doc = QPdfDocument(self)

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.b_prev = QPushButton("◀  Önceki")
        self.b_next = QPushButton("Sonraki  ▶")
        self.b_prev.setToolTip("Listede önceki dosya (← tuşu)")
        self.b_next.setToolTip("Listede sonraki dosya (→ tuşu)")
        self.name = QLabel()
        self.name.setStyleSheet(f"font-weight:600; color:{theme.NAVY};")
        self.b_out = QPushButton("－")
        self.b_in = QPushButton("＋")
        self.zoom_label = QLabel()
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.b_width = QPushButton("Genişliğe Sığdır")
        self.b_page = QPushButton("Sayfaya Sığdır")
        self.page_label = QLabel()
        self.page_label.setStyleSheet(f"color:{theme.MUTED};")
        bar.addWidget(self.b_prev)
        bar.addWidget(self.b_next)
        bar.addSpacing(8)
        bar.addWidget(self.name, 1)
        bar.addWidget(self.page_label)
        bar.addSpacing(8)
        bar.addWidget(self.b_out)
        bar.addWidget(self.zoom_label)
        bar.addWidget(self.b_in)
        bar.addWidget(self.b_width)
        bar.addWidget(self.b_page)
        root.addLayout(bar)

        self.view = QPdfView(self)
        self.view.setDocument(self.doc)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.setStyleSheet("background:#5b6875;")
        root.addWidget(self.view, 1)

        self.message = QLabel()
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setStyleSheet("color:#b3261e; font-weight:600; padding:20px;")
        self.message.hide()
        root.addWidget(self.message)

        self.b_prev.clicked.connect(lambda: self._go(-1))
        self.b_next.clicked.connect(lambda: self._go(1))
        self.b_in.clicked.connect(lambda: self._zoom(ZOOM_STEP))
        self.b_out.clicked.connect(lambda: self._zoom(1 / ZOOM_STEP))
        self.b_width.clicked.connect(lambda: self._fit(QPdfView.ZoomMode.FitToWidth))
        self.b_page.clicked.connect(lambda: self._fit(QPdfView.ZoomMode.FitInView))
        self.view.zoomFactorChanged.connect(self._show_zoom)
        self.view.pageNavigator().currentPageChanged.connect(self._show_page)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self._go(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self._go(1))
        QShortcut(QKeySequence.ZoomIn, self, activated=lambda: self._zoom(ZOOM_STEP))
        QShortcut(QKeySequence.ZoomOut, self, activated=lambda: self._zoom(1 / ZOOM_STEP))

    def show_file(self, path: str, password: str = "", position: str = "") -> None:
        self.doc.close()
        self.doc.setPassword(password)
        self.doc.load(path)
        ok = self.doc.status() == QPdfDocument.Status.Ready
        self.view.setVisible(ok)
        self.message.setVisible(not ok)
        if not ok:
            self.message.setText(f"PDF görüntülenemedi ({self.doc.error().name}).")
        self.name.setText(f"{os.path.basename(path)}  {position}".strip())
        self.name.setToolTip(path)
        self.setWindowTitle(f"PDF Önizleme — {os.path.basename(path)}")
        self.view.pageNavigator().jump(0, QPointF(0, 0))
        self._show_page(0)
        self._show_zoom()

    def set_nav_enabled(self, has_prev: bool, has_next: bool) -> None:
        self.b_prev.setEnabled(has_prev)
        self.b_next.setEnabled(has_next)

    def _go(self, step: int) -> None:
        if self._navigate:
            self._navigate(step)

    def _zoom(self, factor: float) -> None:
        current = self.view.zoomFactor()
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(max(0.1, min(8.0, current * factor)))

    def _fit(self, mode) -> None:
        self.view.setZoomMode(mode)

    def _show_zoom(self, *_) -> None:
        self.zoom_label.setText(f"%{round(self.view.zoomFactor() * 100)}")

    def _show_page(self, page: int) -> None:
        n = self.doc.pageCount()
        self.page_label.setText(f"Sayfa {page + 1} / {n}" if n else "")
