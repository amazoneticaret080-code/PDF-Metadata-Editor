"""Online Düzenleme sekmesi: 10-15 PDF'i listeden seçip tek tek düzenleme ve toplu kaydetme."""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .preview import PdfPreview

COLOR_CHANGED = QColor("#c77700")
COLOR_SAVED = QColor("#1b873f")
COLOR_SIGNED = QColor(theme.MUTED)


def _pdfs_from_mime(mime) -> list[str]:
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.toLocalFile().lower().endswith(".pdf")]


class MultiEditor(QWidget):
    """Solda dosya listesi, sağda seçili dosyanın Tek Dosya Düzenle paneli.

    make_editor() -> SingleEditor(embedded=True) üretir; her dosyanın kendi paneli,
    geri al geçmişi ve kaydetme durumu vardır.
    """

    templates_changed = Signal()

    def __init__(self, make_editor, output, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._make_editor = make_editor
        self.output = output
        self._preview: PdfPreview | None = None
        root = QHBoxLayout(self)

        # --- sol: dosyalar ---
        left = QGroupBox("Dosyalar")
        self.left_box = left
        ll = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.setToolTip("Tıkla: düzenle · Çift tıkla veya Boşluk: görüntüle · Sağ tık: diğer işlemler")
        ll.addWidget(self.list, 1)

        row = QHBoxLayout()
        b_add = QPushButton("+ PDF Ekle")
        self.b_view = QPushButton("👁  Görüntüle")
        self.b_view.setToolTip("Seçili PDF'in içeriğini uygulama içinde gösterir (Boşluk tuşu).")
        row.addWidget(b_add)
        row.addWidget(self.b_view)
        ll.addLayout(row)
        row2 = QHBoxLayout()
        self.b_remove = QPushButton("− Listeden Çıkar")
        b_clear = QPushButton("Listeyi Temizle")
        row2.addWidget(self.b_remove)
        row2.addWidget(b_clear)
        ll.addLayout(row2)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"color:{theme.MUTED}; font-weight:400;")
        ll.addWidget(self.summary)
        self.b_save_all = QPushButton("💾  Tümünü Kaydet")
        self.b_save_all.setProperty("primary", True)
        self.b_save_all.setMinimumHeight(38)
        self.b_save_all.setToolTip("Kaydedilmemiş tüm dosyaları soru sormadan çıktı klasörüne kaydeder.")
        b_out = QPushButton("📁  Çıktı Klasörünü Aç")
        ll.addWidget(self.b_save_all)
        ll.addWidget(b_out)
        root.addWidget(left, 1)

        # --- sağ: seçili dosyanın düzenleyicisi ---
        self.stack = QStackedWidget()
        hint = QLabel(
            "📄  PDF'leri bu pencereye sürükleyip bırakın veya <b>+ PDF Ekle</b> ile seçin.<br><br>"
            "Listeden bir dosyaya tıklayınca düzenleme paneli burada açılır.<br>"
            "Her dosyayı kendi <b>Kaydet</b> düğmesiyle ya da hepsini <b>Tümünü Kaydet</b> ile kaydedebilirsiniz."
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"border:2px dashed {theme.BORDER}; border-radius:8px; color:{theme.MUTED}; background:white; padding:24px;"
        )
        self.stack.addWidget(hint)
        root.addWidget(self.stack, 4)

        b_add.clicked.connect(self._choose_files)
        self.b_view.clicked.connect(self.preview_current)
        self.b_remove.clicked.connect(self._remove_current)
        b_clear.clicked.connect(self._clear)
        self.b_save_all.clicked.connect(self.save_all)
        b_out.clicked.connect(output.open)
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemDoubleClicked.connect(lambda *_: self.preview_current())
        self.list.customContextMenuRequested.connect(self._context_menu)
        QShortcut(QKeySequence(Qt.Key_Space), self.list, activated=self.preview_current,
                  context=Qt.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key_Delete), self.list, activated=self._remove_current,
                  context=Qt.WidgetShortcut)
        QShortcut(QKeySequence("Ctrl+PgDown"), self, activated=lambda: self._step(1),
                  context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+PgUp"), self, activated=lambda: self._step(-1),
                  context=Qt.WidgetWithChildrenShortcut)
        self._update_summary()

    # ------------------------------------------------------------------ #
    # Dosya listesi
    # ------------------------------------------------------------------ #
    def editors(self) -> list:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def current_editor(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def dragEnterEvent(self, e):
        if _pdfs_from_mime(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths(_pdfs_from_mime(e.mimeData()))

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF seç", "", "PDF dosyaları (*.pdf)")
        self.add_paths(paths)

    def add_paths(self, paths: list[str]) -> None:
        existing = {os.path.normcase(e.doc.path) for e in self.editors()}
        first_new = None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for path in paths:
                path = os.path.normpath(path)
                if os.path.normcase(path) in existing:
                    continue
                QApplication.restoreOverrideCursor()  # şifre sorulursa normal imleç
                editor = self._make_editor()
                self.stack.addWidget(editor)  # yüklemeden önce pencereye bağlı olmalı (durum çubuğu)
                editor.load(path)
                QApplication.setOverrideCursor(Qt.WaitCursor)
                if editor.doc is None:  # açılamadı veya şifre girilmedi
                    self.stack.removeWidget(editor)
                    editor.deleteLater()
                    continue
                existing.add(os.path.normcase(path))
                item = QListWidgetItem()
                item.setData(Qt.UserRole, editor)
                item.setToolTip(path)
                self.list.addItem(item)
                editor.state_changed.connect(lambda e=editor: self._refresh_item(e))
                editor.tpl_bar.store_changed.connect(self.templates_changed)
                self._refresh_item(editor)
                if first_new is None:
                    first_new = self.list.count() - 1
                QApplication.processEvents()
        finally:
            QApplication.restoreOverrideCursor()
        if first_new is not None and self.list.currentRow() < 0:
            self.list.setCurrentRow(first_new)
        self._update_summary()

    def _item_for(self, editor) -> QListWidgetItem | None:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) is editor:
                return self.list.item(i)
        return None

    def _refresh_item(self, editor) -> None:
        item = self._item_for(editor)
        if item is None or editor.doc is None:
            return
        name = os.path.basename(editor.doc.path)
        if editor.doc.signed_by:
            text, color, tip = f"🔒  {name}", COLOR_SIGNED, "İmzalı belge — değiştirilemez"
        elif editor.saved_path and not editor.needs_save():
            text, color, tip = f"✔  {name}", COLOR_SAVED, f"Kaydedildi: {editor.saved_path}"
        elif editor.is_modified() or editor.saved_path:
            text, color, tip = f"●  {name}", COLOR_CHANGED, "Değiştirildi, kaydedilmedi"
        else:
            text, color, tip = f"○  {name}", QColor(theme.TEXT), "Değişiklik yok, kaydedilmedi"
        item.setText(text)
        item.setForeground(QBrush(color))
        item.setToolTip(f"{editor.doc.path}\n{tip}")
        self._update_summary()

    def _update_summary(self) -> None:
        eds = self.editors()
        n = len(eds)
        self.left_box.setTitle(f"Dosyalar ({n})")
        if not n:
            self.summary.setText("Liste boş.")
        else:
            changed = sum(1 for e in eds if e.needs_save() and e.is_modified())
            pending = sum(1 for e in eds if e.needs_save())
            saved = sum(1 for e in eds if e.saved_path and not e.needs_save())
            signed = sum(1 for e in eds if e.doc.signed_by)
            parts = [f"● {changed} değişti", f"✔ {saved} kaydedildi"]
            if signed:
                parts.append(f"🔒 {signed} imzalı")
            self.summary.setText("  ·  ".join(parts))
            self.b_save_all.setText(f"💾  Tümünü Kaydet ({pending})")
        if not n:
            self.b_save_all.setText("💾  Tümünü Kaydet")
        has = self.list.currentItem() is not None
        for b in (self.b_view, self.b_remove):
            b.setEnabled(has)
        self.b_save_all.setEnabled(n > 0)

    def _on_row(self, row: int) -> None:
        editor = self.current_editor()
        self.stack.setCurrentWidget(editor if editor else self.stack.widget(0))
        self._update_summary()
        if editor and self._preview and self._preview.isVisible():
            self.preview_current()

    def _step(self, step: int) -> None:
        n = self.list.count()
        if n:
            self.list.setCurrentRow(max(0, min(n - 1, self.list.currentRow() + step)))

    def _confirm_discard(self, editors: list) -> bool:
        unsaved = [e for e in editors if e.needs_save() and e.is_modified()]
        if not unsaved:
            return True
        names = "\n".join("• " + os.path.basename(e.doc.path) for e in unsaved[:10])
        return QMessageBox.question(
            self, "Kaydedilmemiş değişiklikler",
            f"Şu dosyalardaki değişiklikler kaydedilmedi:\n{names}\n\nYine de listeden çıkarılsın mı?",
        ) == QMessageBox.Yes

    def _remove_editor(self, editor) -> None:
        item = self._item_for(editor)
        if item:
            self.list.takeItem(self.list.row(item))
        self.stack.removeWidget(editor)
        editor.deleteLater()

    def _remove_current(self) -> None:
        editor = self.current_editor()
        if editor and self._confirm_discard([editor]):
            self._remove_editor(editor)
            self._update_summary()

    def _clear(self) -> None:
        eds = self.editors()
        if eds and self._confirm_discard(eds):
            for e in eds:
                self._remove_editor(e)
            self._update_summary()

    def has_unsaved(self) -> bool:
        return any(e.needs_save() and e.is_modified() for e in self.editors())

    def refresh_templates(self) -> None:
        for e in self.editors():
            e.tpl_bar.refresh()

    def _context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if not item:
            return
        self.list.setCurrentItem(item)
        editor = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction(QAction("👁  Görüntüle", menu, triggered=self.preview_current))
        a_save = QAction("💾  Kaydet…", menu, triggered=editor.save)
        a_save.setEnabled(not editor.doc.signed_by)
        menu.addAction(a_save)
        menu.addSeparator()
        menu.addAction(QAction("Kaynak dosyayı klasörde göster", menu,
                               triggered=lambda: self._reveal(editor.doc.path)))
        if editor.saved_path:
            menu.addAction(QAction("Kaydedilen dosyayı klasörde göster", menu,
                                   triggered=lambda: self._reveal(editor.saved_path)))
        menu.addSeparator()
        menu.addAction(QAction("− Listeden çıkar", menu, triggered=self._remove_current))
        menu.exec(self.list.viewport().mapToGlobal(pos))

    @staticmethod
    def _reveal(path: str) -> None:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    # ------------------------------------------------------------------ #
    # Önizleme
    # ------------------------------------------------------------------ #
    def preview_current(self) -> None:
        editor = self.current_editor()
        if not editor:
            return
        if self._preview is None:
            self._preview = PdfPreview(self.window(), navigate=self._step)
        row, n = self.list.currentRow(), self.list.count()
        self._preview.show_file(editor.doc.path, editor.password, f"({row + 1}/{n})")
        self._preview.set_nav_enabled(row > 0, row < n - 1)
        self._preview.show()
        self._preview.raise_()
        self._preview.activateWindow()

    # ------------------------------------------------------------------ #
    # Toplu kaydetme
    # ------------------------------------------------------------------ #
    def save_all(self) -> None:
        eds = self.editors()
        if not eds:
            return
        pending = [e for e in eds if e.needs_save()]
        changed = [e for e in pending if e.is_modified()]
        if not pending:
            QMessageBox.information(self, "Tümünü Kaydet", "Kaydedilecek dosya yok; hepsi kaydedildi veya imzalı.")
            return
        sign = eds[0].sign
        text = f"Çıktı klasörü:\n{self.output.path()}"
        if sign.note():
            text += "\n\n" + sign.note().replace("Belge", "Her belge", 1)
        box = QMessageBox(QMessageBox.Question, "Tümünü Kaydet", text, parent=self)
        b_all = box.addButton(f"Tümünü Kaydet ({len(pending)})", QMessageBox.AcceptRole)
        b_changed = None
        if changed and len(changed) != len(pending):
            b_changed = box.addButton(f"Yalnızca Değişenler ({len(changed)})", QMessageBox.AcceptRole)
        box.addButton("İptal", QMessageBox.RejectRole)
        box.setDefaultButton(b_all)
        box.exec()
        if box.clickedButton() is b_all:
            targets = pending
        elif b_changed is not None and box.clickedButton() is b_changed:
            targets = changed
        else:
            return
        self._save_editors(targets)

    def _save_editors(self, targets: list) -> None:
        ok, errors = [], []
        status = self.window().statusBar()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, editor in enumerate(targets, 1):
                name = os.path.basename(editor.doc.path)
                status.showMessage(f"Kaydediliyor {i}/{len(targets)}: {name}")
                QApplication.processEvents()
                try:
                    dst, signed = editor.save_to_output()
                    ok.append(f"✔ {'🔒 ' if signed else ''}{name}  →  {os.path.basename(dst)}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"✖ {name}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        status.showMessage(f"Toplu kayıt bitti: {len(ok)}/{len(targets)} başarılı", 10000)
        self._update_summary()
        box = QMessageBox(
            QMessageBox.Warning if errors else QMessageBox.Information,
            "Tümünü Kaydet",
            f"{len(ok)}/{len(targets)} dosya kaydedildi.\nKlasör: {self.output.path()}",
            parent=self,
        )
        box.setInformativeText("\n".join(errors + ok))
        b_open = box.addButton("📁 Klasörü Aç", QMessageBox.ActionRole)
        box.addButton("Tamam", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is b_open:
            self.output.open()
