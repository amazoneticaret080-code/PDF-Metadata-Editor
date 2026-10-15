"""Belge Okuyucu sekmesi: PDF'lerin tüm verilerini gösterir, kopyalatır ve şablon olarak kaydeder."""
from __future__ import annotations

import os

import pikepdf
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import core, theme
from .preview import PdfPreview
from .reader import Report, read_report
from .templates import TemplateStore


def _pdfs(mime) -> list[str]:
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.toLocalFile().lower().endswith(".pdf")]


class SaveTemplateDialog(QDialog):
    """Şablon adı ve neyin kaydedileceği."""

    def __init__(self, parent, report: Report, existing: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Bilgileri şablon olarak kaydet")
        self.report = report
        self.existing = existing
        lay = QVBoxLayout(self)
        form = QFormLayout()
        title = next((e.value for e in report.doc.info if e.key == "/Title" and e.value), "")
        self.name = QLineEdit(title or os.path.splitext(os.path.basename(report.path))[0])
        self.name.selectAll()
        form.addRow("Şablon adı:", self.name)
        lay.addLayout(form)
        self.chk_dates = QCheckBox("Oluşturma / değiştirme tarihlerini de kaydet")
        self.chk_custom = QCheckBox("Özel (standart dışı) Info alanlarını da kaydet")
        self.chk_xmp = QCheckBox("XMP metadata'yı da kaydet")
        for c in (self.chk_dates, self.chk_custom, self.chk_xmp):
            c.setChecked(True)
            c.toggled.connect(self._update)
            lay.addWidget(c)
        has_custom = any(e.key not in core.STANDARD_KEYS and e.kind != core.KIND_OTHER for e in report.doc.info)
        self.chk_custom.setEnabled(has_custom)
        self.chk_xmp.setEnabled(bool(report.doc.xmp.strip()))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            f"background:#f7f9fb; border:1px solid {theme.BORDER}; border-radius:6px; padding:8px; font-weight:400;"
        )
        lay.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("💾  Kaydet")
        buttons.button(QDialogButtonBox.Save).setProperty("primary", True)
        buttons.button(QDialogButtonBox.Cancel).setText("İptal")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.resize(520, 0)
        self._update()

    def data(self) -> dict:
        return self.report.template(
            include_dates=self.chk_dates.isChecked(),
            include_custom=self.chk_custom.isChecked() and self.chk_custom.isEnabled(),
            include_xmp=self.chk_xmp.isChecked() and self.chk_xmp.isEnabled(),
        )

    def _update(self, *_) -> None:
        d = self.data()
        labels = [core.LABELS.get(k, k) for k in d["fields"]]
        parts = [f"<b>{len(d['fields'])} standart alan</b>: {', '.join(labels) or '—'}"]
        if d["custom"]:
            parts.append(f"<b>{len(d['custom'])} özel alan</b>: {', '.join(r[0] for r in d['custom'])}")
        if d.get("xmp"):
            parts.append("<b>XMP</b>: tamamı")
        self.summary.setText("<br>".join(parts))

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.information(self, "Şablon", "Şablon adı girin.")
            return
        d = self.data()
        if not d["fields"] and not d["custom"] and not d.get("xmp"):
            QMessageBox.information(self, "Şablon", "Belgede kaydedilecek metadata yok.")
            return
        if name in self.existing and QMessageBox.question(
            self, "Şablon", f"'{name}' şablonu zaten var. Üzerine yazılsın mı?"
        ) != QMessageBox.Yes:
            return
        self.accept()


class ReaderPanel(QWidget):
    templates_changed = Signal()
    open_requested = Signal(str, str)  # yol, şifre -> Tek Dosya Düzenle'de aç

    def __init__(self, store: TemplateStore, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.store = store
        self._reports: dict[str, tuple[Report, str]] = {}
        self._preview: PdfPreview | None = None
        root = QHBoxLayout(self)

        # --- sol: belgeler ---
        left = QGroupBox("Belgeler")
        ll = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.setToolTip("PDF'leri buraya sürükleyip bırakabilirsiniz.")
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        b_add = QPushButton("+ PDF Ekle")
        b_rem = QPushButton("− Çıkar")
        b_clr = QPushButton("Temizle")
        row.addWidget(b_add)
        row.addWidget(b_rem)
        row.addWidget(b_clr)
        ll.addLayout(row)
        root.addWidget(left, 1)

        # --- sağ: veriler ---
        right = QVBoxLayout()
        self.title = QLabel("📄  PDF ekleyin veya bu pencereye sürükleyip bırakın.")
        self.title.setStyleSheet(
            f"padding:10px; border:2px dashed {theme.BORDER}; border-radius:8px; background:white;"
            f" color:{theme.MUTED};"
        )
        self.title.setWordWrap(True)
        right.addWidget(self.title)

        actions = QHBoxLayout()
        self.b_save_tpl = QPushButton("💾  Bilgileri Şablon Olarak Kaydet")
        self.b_save_tpl.setProperty("primary", True)
        self.b_save_tpl.setToolTip(
            "Bu belgenin metadata'sını (Info + XMP) tek tıkla şablon olarak kaydeder.\n"
            "Diğer sekmelerde Şablon listesinden seçip 'Uygula' ile yeni belgelere aktarabilirsiniz."
        )
        self.b_copy_all = QPushButton("📋  Tümünü Kopyala")
        self.b_copy_sel = QPushButton("📋  Seçiliyi Kopyala")
        self.b_copy_xmp = QPushButton("📋  Ham XMP'yi Kopyala")
        self.b_view = QPushButton("👁  Görüntüle")
        self.b_edit = QPushButton("✏  Tek Dosya Düzenle'de Aç")
        for b in (self.b_save_tpl, self.b_copy_all, self.b_copy_sel, self.b_copy_xmp, self.b_view, self.b_edit):
            actions.addWidget(b)
        actions.addStretch(1)
        right.addLayout(actions)

        self.tabs = QTabWidget()
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Özellik", "Değer"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.header().setStretchLastSection(True)
        self.tree.setColumnWidth(0, 300)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setWordWrap(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.setToolTip("Çift tıklama: değeri kopyalar · Ctrl+C: seçili satırları kopyalar")
        self.tabs.addTab(self.tree, "Tüm Bilgiler")
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 10))
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.tabs.addTab(self.text, "Metin Olarak")
        self.xmp = QPlainTextEdit()
        self.xmp.setReadOnly(True)
        self.xmp.setFont(QFont("Consolas", 10))
        self.xmp.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.tabs.addTab(self.xmp, "Ham XMP")
        right.addWidget(self.tabs, 1)
        root.addLayout(right, 4)

        b_add.clicked.connect(self._choose)
        b_rem.clicked.connect(self._remove)
        b_clr.clicked.connect(self._clear)
        self.list.currentRowChanged.connect(self._show_current)
        self.b_save_tpl.clicked.connect(self.save_template)
        self.b_copy_all.clicked.connect(self.copy_all)
        self.b_copy_sel.clicked.connect(self.copy_selected)
        self.b_copy_xmp.clicked.connect(lambda: self._copy(self.xmp.toPlainText(), "Ham XMP"))
        self.b_view.clicked.connect(self._view)
        self.b_edit.clicked.connect(self._open_in_editor)
        self.tree.itemDoubleClicked.connect(self._copy_value)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        QShortcut(QKeySequence.Copy, self.tree, activated=self.copy_selected, context=Qt.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key_Delete), self.list, activated=self._remove, context=Qt.WidgetShortcut)
        self._set_enabled(False)

    # ------------------------------------------------------------------ #
    def dragEnterEvent(self, e):
        if _pdfs(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths(_pdfs(e.mimeData()))

    def _choose(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF seç", "", "PDF dosyaları (*.pdf)")
        self.add_paths(paths)

    def add_paths(self, paths: list[str]) -> None:
        first = None
        for path in paths:
            path = os.path.normpath(path)
            key = os.path.normcase(path)
            if key in self._reports:
                continue
            report = self._read(path)
            if report is None:
                continue
            self._reports[key] = report
            item = QListWidgetItem(("🔒  " if report[0].doc.signed_by else "📄  ") + os.path.basename(path))
            item.setData(Qt.UserRole, key)
            item.setToolTip(path)
            self.list.addItem(item)
            if first is None:
                first = self.list.count() - 1
        if first is not None:
            self.list.setCurrentRow(first)

    def _read(self, path: str) -> tuple[Report, str] | None:
        password = ""
        while True:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                return read_report(path, password), password
            except (core.PasswordRequired, pikepdf.PasswordError):
                QApplication.restoreOverrideCursor()
                pw, ok = QInputDialog.getText(
                    self, "Şifreli PDF", f"{os.path.basename(path)} şifreli.\nŞifreyi girin:", QLineEdit.Password
                )
                if not ok:
                    return None
                password = pw
                continue
            except Exception as exc:  # noqa: BLE001
                QApplication.restoreOverrideCursor()
                QMessageBox.critical(self, "PDF okunamadı", f"{os.path.basename(path)}:\n{exc}")
                return None
            finally:
                if QApplication.overrideCursor() is not None:
                    QApplication.restoreOverrideCursor()

    def _current(self) -> tuple[Report, str] | None:
        item = self.list.currentItem()
        return self._reports.get(item.data(Qt.UserRole)) if item else None

    def _remove(self) -> None:
        item = self.list.currentItem()
        if item:
            self._reports.pop(item.data(Qt.UserRole), None)
            self.list.takeItem(self.list.row(item))
            if not self.list.count():
                self._show_current(-1)

    def _clear(self) -> None:
        self._reports.clear()
        self.list.clear()
        self._show_current(-1)

    def _set_enabled(self, on: bool) -> None:
        for b in (self.b_save_tpl, self.b_copy_all, self.b_copy_sel, self.b_copy_xmp, self.b_view, self.b_edit):
            b.setEnabled(on)

    def _show_current(self, _row: int) -> None:
        cur = self._current()
        self.tree.clear()
        self.text.clear()
        self.xmp.clear()
        self._set_enabled(cur is not None)
        if cur is None:
            self.title.setText("📄  PDF ekleyin veya bu pencereye sürükleyip bırakın.")
            return
        report, _ = cur
        lock = "   ·   🔒 dijital imzalı" if report.doc.signed_by else ""
        self.title.setText(f"📄  {report.path}{lock}")
        self.title.setStyleSheet(
            f"padding:10px; border:1px solid {theme.BORDER}; border-left:4px solid {theme.BLUE};"
            f" border-radius:8px; background:white; font-weight:600;"
        )
        bold = QFont()
        bold.setBold(True)
        for title, rows in report.sections:
            count = sum(1 for k, _ in rows if k not in ("—", "…"))
            sec = QTreeWidgetItem([f"{title}  ({count})", ""])
            sec.setFont(0, bold)
            sec.setFirstColumnSpanned(False)
            sec.setData(0, Qt.UserRole, "section")
            self.tree.addTopLevelItem(sec)
            for key, value in rows:
                child = QTreeWidgetItem([key, value])
                child.setToolTip(1, value)
                sec.addChild(child)
            sec.setExpanded(True)
        self.text.setPlainText(report.as_text())
        self.xmp.setPlainText(report.doc.xmp.strip() or "(Bu belgede XMP yok)")
        self.b_copy_xmp.setEnabled(bool(report.doc.xmp.strip()))

    # ------------------------------------------------------------------ #
    # Kopyalama
    # ------------------------------------------------------------------ #
    def _copy(self, text: str, what: str) -> None:
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.window().statusBar().showMessage(f"Kopyalandı: {what}", 4000)

    def copy_all(self) -> None:
        cur = self._current()
        if cur:
            self._copy(cur[0].as_text(), "tüm bilgiler")

    @staticmethod
    def _row_text(item: QTreeWidgetItem) -> list[str]:
        if item.data(0, Qt.UserRole) == "section":
            lines = [f"=== {item.text(0)} ==="]
            lines += [f"{item.child(i).text(0)} : {item.child(i).text(1)}" for i in range(item.childCount())]
            return lines
        return [f"{item.text(0)} : {item.text(1)}"]

    def copy_selected(self) -> None:
        items = self.tree.selectedItems()
        if not items and self.tabs.currentWidget() is not self.tree:
            widget = self.tabs.currentWidget()
            self._copy(widget.textCursor().selectedText().replace(" ", "\n"), "seçili metin")
            return
        lines = []
        for item in items:
            lines += self._row_text(item)
        self._copy("\n".join(lines), f"{len(items)} satır")

    def _copy_value(self, item: QTreeWidgetItem, _col: int) -> None:
        if item.data(0, Qt.UserRole) != "section":
            self._copy(item.text(1), item.text(0))

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        if item.data(0, Qt.UserRole) == "section":
            menu.addAction(QAction("Bölümü kopyala", menu,
                                   triggered=lambda: self._copy("\n".join(self._row_text(item)), item.text(0))))
        else:
            menu.addAction(QAction("Değeri kopyala", menu, triggered=lambda: self._copy(item.text(1), item.text(0))))
            menu.addAction(QAction("Özellik adını kopyala", menu,
                                   triggered=lambda: self._copy(item.text(0), item.text(0))))
            menu.addAction(QAction("Satırı kopyala", menu,
                                   triggered=lambda: self._copy(f"{item.text(0)} : {item.text(1)}", item.text(0))))
            parent = item.parent()
            menu.addAction(QAction("Bölümün tamamını kopyala", menu,
                                   triggered=lambda: self._copy("\n".join(self._row_text(parent)), parent.text(0))))
        menu.addSeparator()
        menu.addAction(QAction("Seçili satırları kopyala", menu, triggered=self.copy_selected))
        menu.addAction(QAction("Tümünü kopyala", menu, triggered=self.copy_all))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ #
    # Şablon, görüntüleme, düzenleme
    # ------------------------------------------------------------------ #
    def save_template(self) -> None:
        cur = self._current()
        if not cur:
            return
        dlg = SaveTemplateDialog(self, cur[0], self.store.names())
        if not dlg.exec():
            return
        name = dlg.name.text().strip()
        try:
            self.store.put(name, dlg.data())
        except OSError as exc:
            QMessageBox.critical(self, "Şablon kaydedilemedi", str(exc))
            return
        self.templates_changed.emit()
        self.window().statusBar().showMessage(f"Şablon kaydedildi: {name}", 6000)
        QMessageBox.information(
            self, "Şablon kaydedildi",
            f"'{name}' şablonu kaydedildi.\n\n"
            "Tek Dosya Düzenle, Toplu Düzenleme veya Online Düzenleme sekmesinde Şablon listesinden "
            "seçip 'Uygula'ya basarak bu bilgileri yeni belgelere aktarabilirsiniz.",
        )

    def _view(self) -> None:
        cur = self._current()
        if not cur:
            return
        if self._preview is None:
            self._preview = PdfPreview(self.window())
        self._preview.set_nav_enabled(False, False)
        self._preview.show_file(cur[0].path, cur[1])
        self._preview.show()
        self._preview.raise_()
        self._preview.activateWindow()

    def _open_in_editor(self) -> None:
        cur = self._current()
        if cur:
            self.open_requested.emit(cur[0].path, cur[1])

    def refresh_current(self) -> None:
        """Dosya diskte değiştiyse yeniden okur."""
        cur = self._current()
        if cur:
            fresh = self._read(cur[0].path)
            if fresh:
                self._reports[self.list.currentItem().data(Qt.UserRole)] = fresh
                self._show_current(self.list.currentRow())
