"""PDF Metadata Düzenleyici - ana pencere."""
from __future__ import annotations

import os
import subprocess
import sys
import traceback

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import core, signing, theme
from .compress_ui import CompressPanel
from .lang_ui import LangBar, LanguageChoice
from .multi import MultiEditor
from .reader_ui import ReaderPanel
from .sign_ui import SignaturePanel, SignBar, SignChoice
from .templates import TemplateStore
from .widgets import DateField, DiffDialog, KeyValueTable, TemplateBar, diff_rows

APP_NAME = "PDF Metadata Düzenleyici"
INFO_KINDS = [core.KIND_STRING, core.KIND_NAME, core.KIND_OTHER]
XMP_KINDS = [core.XMP_TEXT, core.XMP_LIST, core.XMP_SET]
TRAPPED_CHOICES = ["", "True", "False", "Unknown"]
HISTORY_LIMIT = 200
OUTPUT_DIR_NAME = "çıktı belgeleri"
OUTPUT_SUFFIX = "_duzenlenmis"


def _program_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


INSTALLED_MARKER = "kurulum.ini"  # kurulum programı uygulama klasörüne yazar


def _default_output_dir() -> str:
    """Taşınabilir kullanımda programın yanı; kurulu sürümde Belgeler klasörü.

    Kurulu programın klasörüne yazmak kullanıcıyı şaşırtır (ve kaldırmada silinir).
    """
    prog = _program_dir()
    installed = os.path.exists(os.path.join(prog, INSTALLED_MARKER))
    if not installed and os.access(prog, os.W_OK):
        return os.path.join(prog, OUTPUT_DIR_NAME)
    from PySide6.QtCore import QStandardPaths

    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
    return os.path.join(docs, APP_NAME, OUTPUT_DIR_NAME)


def _unique_path(folder: str, filename: str) -> str:
    """Klasörde aynı adlı dosya varsa 'ad (2).pdf', 'ad (3).pdf' … döndürür."""
    name, ext = os.path.splitext(filename)
    path = os.path.join(folder, filename)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{name} ({n}){ext}")
        n += 1
    return path


def _reveal_in_explorer(path: str) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        QMessageBox.information(None, APP_NAME, path)


class OutputFolder(QObject):
    """Çıktı klasörü ayarı (kalıcı); tek dosya ve toplu sekme bunu paylaşır."""

    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("SuspendGlobal", "PDFMetadataDuzenleyici")
        default = _default_output_dir()
        self._path = str(self._settings.value("output_dir", default) or default)

    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        path = os.path.normpath(path) if path else ""
        if path and path != self._path:
            self._path = path
            self._settings.setValue("output_dir", path)
            self.changed.emit(path)

    def ensure(self) -> str:
        os.makedirs(self._path, exist_ok=True)
        return self._path

    def choose(self, parent) -> None:
        d = QFileDialog.getExistingDirectory(parent, "Çıktı klasörünü seç", self._path)
        if d:
            self.set_path(d)

    def open(self) -> None:
        if sys.platform == "win32":
            os.startfile(self.ensure())


def _pdf_paths_from_mime(mime) -> list[str]:
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls() if u.toLocalFile().lower().endswith(".pdf")]


def _ask_password(parent, path: str) -> str | None:
    pw, ok = QInputDialog.getText(
        parent, "Şifreli PDF", f"{os.path.basename(path)} şifreli.\nŞifreyi girin:", QLineEdit.Password
    )
    return pw if ok else None


def _show_error(parent, title: str, exc: Exception) -> None:
    box = QMessageBox(QMessageBox.Critical, title, str(exc) or exc.__class__.__name__, parent=parent)
    box.setDetailedText(traceback.format_exc())
    box.exec()


def _make_field_editor(key: str) -> QWidget:
    if key in core.DATE_KEYS:
        return DateField()
    if key == "/Trapped":
        ed = QComboBox()
        ed.setEditable(True)
        ed.addItems(TRAPPED_CHOICES)
        return ed
    ed = QLineEdit()
    ed.setClearButtonEnabled(True)
    return ed


def _editor_value(ed: QWidget) -> tuple[str, str]:
    """Standart alan düzenleyicisinden (değer, tür) okur."""
    if isinstance(ed, DateField):
        return ed.get_raw(), core.KIND_STRING
    if isinstance(ed, QComboBox):
        return ed.currentText().strip(), core.KIND_NAME
    return ed.text(), core.KIND_STRING


def _set_editor_value(ed: QWidget, value: str) -> None:
    if isinstance(ed, DateField):
        ed.set_raw(value)
    elif isinstance(ed, QComboBox):
        ed.setCurrentText(value)
    else:
        ed.setText(value)


def _field_label(key: str) -> str:
    return f"{core.LABELS[key]} ({key[1:]})" if key in core.LABELS else key


def _display_value(key: str, value: str) -> str:
    """Karşılaştırmada tarihleri okunur biçimde de gösterir."""
    if key in core.DATE_KEYS and value:
        parsed = core.parse_pdf_date(value)
        if parsed:
            tz = parsed.strftime(" %z") if parsed.utcoffset() is not None else ""
            return f"{value}  ({parsed.strftime('%d.%m.%Y %H:%M:%S')}{tz})"
    return value


def _info_rows(entries: list[core.InfoEntry]) -> list[tuple[str, str, str]]:
    """Info girdilerini standart alanlar önde olacak şekilde karşılaştırma satırlarına çevirir."""
    rows = {}
    for e in entries:
        key = core._normalize_key(e.key)
        if key != "/":
            rows[key] = (key, _display_value(key, e.value), e.kind)
    order = [k for k in core.STANDARD_KEYS if k in rows] + [k for k in rows if k not in core.STANDARD_KEYS]
    return [rows[k] for k in order]


# =========================================================================== #
# Tek dosya düzenleyici
# =========================================================================== #


class SingleEditor(QWidget):
    # düzenleme, kaydetme veya yükleme sonrası (Online Düzenleme listesindeki durum için)
    state_changed = Signal()

    def __init__(
        self, store: TemplateStore, output: OutputFolder, sign: SignChoice, lang: LanguageChoice,
        parent=None, embedded: bool = False,
    ):
        super().__init__(parent)
        # embedded: Online Düzenleme sekmesinde dosya listesine bağlı; kendi dosyasını değiştirmez
        self.embedded = embedded
        self.setAcceptDrops(not embedded)
        self.store = store
        self.output = output
        self.sign = sign
        self.lang = lang
        self.saved_path = ""  # son kaydedilen dosya
        self._saved_snap: tuple | None = None
        self.doc: core.DocumentData | None = None
        self.password = ""
        self.xmp_xml = ""
        self._xmp_table_dirty = False
        self._xmp_raw_dirty = False
        self._loading = False

        # geri al / yinele: düzenlemeler kısa bir beklemeden sonra tek adım olarak kaydedilir
        self._restoring = False
        self._history: list[tuple] = []
        self._hist_pos = -1
        self._initial: tuple | None = None
        self._snap_timer = QTimer(self, singleShot=True, interval=500)
        self._snap_timer.timeout.connect(self._take_snapshot)

        root = QVBoxLayout(self)

        # --- üst çubuk ---
        bar = QHBoxLayout()
        self.btn_open = QPushButton("📂  PDF Aç…")
        self.btn_save = QPushButton("💾  Kaydet")
        self.btn_save.setProperty("primary", True)
        self.btn_save.setToolTip(
            "Önce öncesi/sonrası karşılaştırmasını gösterir; onaylayınca yeni dosyayı çıktı klasörüne kaydeder (Ctrl+S)."
        )
        self.btn_diff = QPushButton("🔍  Değişiklikleri Göster")
        self.btn_undo = QPushButton("↶  Geri Al")
        self.btn_redo = QPushButton("↷  Yinele")
        self.btn_reload = QPushButton("↺  Dosyadaki Haline Döndür")
        self.btn_clear = QPushButton("🧹  Tüm Metadatayı Temizle")
        self.btn_diff.setToolTip("Dosyadaki değerlerle ekrandaki değerleri yan yana karşılaştırır.")
        self.btn_undo.setToolTip("Son düzenlemeyi geri alır (Ctrl+Z)")
        self.btn_redo.setToolTip("Geri alınan düzenlemeyi yineler (Ctrl+Y)")
        self.btn_reload.setToolTip("Tüm alanları dosyadan okunan değerlere döndürür (Geri Al ile iptal edilebilir).")
        bar.addWidget(self.btn_open)
        self.btn_open.setVisible(not embedded)
        for b in (self.btn_save, self.btn_diff, self.btn_undo, self.btn_redo, self.btn_reload, self.btn_clear):
            b.setEnabled(False)
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        self.path_label = QLabel("📄  PDF seçin veya bu pencereye sürükleyip bırakın.")
        self.path_label.setStyleSheet(
            f"padding:12px; border:2px dashed {theme.BORDER}; border-radius:8px; color:{theme.MUTED}; background:white;"
        )
        self.path_label.setAlignment(Qt.AlignCenter)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.path_label)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # --- sol: dosya bilgileri ---
        info_box = QGroupBox("Dosya Bilgileri (salt okunur)")
        il = QVBoxLayout(info_box)
        self.file_table = QTableWidget(0, 2)
        self.file_table.setHorizontalHeaderLabels(["Özellik", "Değer"])
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.file_table.setColumnWidth(0, 170)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.setWordWrap(True)
        il.addWidget(self.file_table)
        split.addWidget(info_box)

        # --- sağ: sekmeler ---
        self.tabs = QTabWidget()
        split.addWidget(self.tabs)
        split.setSizes([380, 820])

        self.tabs.addTab(self._build_info_tab(), "Belge Bilgileri (Info)")
        self.tabs.addTab(self._build_xmp_tab(), "XMP Metadata")

        # --- alt seçenekler ---
        opts = QHBoxLayout()
        self.chk_sync = QCheckBox("Kaydederken XMP'yi yalnızca Info alanlarından oluştur")
        self.chk_sync.setToolTip(
            "XMP, Belge Bilgileri (Info) sekmesindeki değerlerden yeniden oluşturulur.\n"
            "Info'da olmayan her şey (ör. eski anahtar kelimeler) XMP'den silinir."
        )
        self.chk_strip_pages = QCheckBox("Sayfa düzeyindeki XMP ve PieceInfo verilerini de sil")
        opts.addWidget(self.chk_sync)
        opts.addWidget(self.chk_strip_pages)
        opts.addStretch(1)
        opts.addWidget(QLabel("Çıktı klasörü:"))
        self.out_label = QLabel()
        self.out_label.setStyleSheet(f"color:{theme.MUTED};")
        self.out_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        b_out = QPushButton("Değiştir…")
        b_out_open = QPushButton("📁  Aç")
        opts.addWidget(self.out_label)
        opts.addWidget(b_out)
        opts.addWidget(b_out_open)
        root.addLayout(opts)
        self._show_output(output.path())
        output.changed.connect(self._show_output)
        b_out.clicked.connect(lambda: output.choose(self))
        b_out_open.clicked.connect(output.open)
        self.lang_bar = LangBar(lang)
        root.addWidget(self.lang_bar)
        self.sign_bar = SignBar(sign)
        root.addWidget(self.sign_bar)

        self.btn_open.clicked.connect(self.choose_file)
        self.btn_save.clicked.connect(self.save)
        self.btn_diff.clicked.connect(self.show_diff)
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo.clicked.connect(self.redo)
        self.btn_reload.clicked.connect(self.revert_to_file)
        self.btn_clear.clicked.connect(self.clear_all)

        self._watch_edits()
        self.tabs.setEnabled(False)

    # ------------------------------------------------------------------ #
    # Info sekmesi
    # ------------------------------------------------------------------ #
    def _build_info_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.tpl_bar = TemplateBar(
            self.store, self._template_collect, self._template_apply,
            apply_tip="Şablondaki alanları ekrana yazar; şablonda olmayan alanlara dokunmaz.",
        )
        lay.addWidget(self.tpl_bar)

        std = QGroupBox("Standart Alanlar")
        form = QFormLayout(std)
        self.fields: dict[str, QWidget] = {}
        for key in core.STANDARD_KEYS:
            ed = _make_field_editor(key)
            self.fields[key] = ed
            form.addRow(f"{core.LABELS[key]}  ({key[1:]}):", ed)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(std)
        lay.addWidget(scroll, 3)

        other = QGroupBox("Diğer / Özel Alanlar")
        ol = QVBoxLayout(other)
        self.custom_table = KeyValueTable(["Anahtar", "Değer", "Tür"], INFO_KINDS)
        ol.addWidget(self.custom_table)
        row = QHBoxLayout()
        add = QPushButton("+ Alan Ekle")
        rem = QPushButton("− Seçili Alanı Sil")
        hint = QLabel("Tür 'diğer' olan alanlar metin dışı PDF nesneleridir; olduğu gibi korunur.")
        hint.setStyleSheet("color:gray;")
        row.addWidget(add)
        row.addWidget(rem)
        row.addWidget(hint, 1)
        ol.addLayout(row)
        add.clicked.connect(self._add_custom)
        rem.clicked.connect(self.custom_table.remove_selected)
        lay.addWidget(other, 2)
        return w

    def _add_custom(self) -> None:
        r = self.custom_table.add_row("/YeniAlan", "", core.KIND_STRING)
        self.custom_table.edited.emit()
        self.custom_table.editItem(self.custom_table.item(r, 0))

    # ------------------------------------------------------------------ #
    # Şablonlar
    # ------------------------------------------------------------------ #
    def _template_collect(self) -> dict:
        fields = {}
        for key, ed in self.fields.items():
            val, _ = _editor_value(ed)
            if val:
                fields[key] = val
        custom = [[k, v, t] for k, v, t in self.custom_table.rows() if t != core.KIND_OTHER]
        return {"fields": fields, "custom": custom}

    def _template_apply(self, data: dict) -> None:
        if not self.doc:
            QMessageBox.information(self, APP_NAME, "Şablonu uygulamak için önce bir PDF açın.")
            return
        self._flush_pending()
        for key, val in data["fields"].items():
            if key in self.fields:
                _set_editor_value(self.fields[key], val)
        rows = {k: (k, v, t) for k, v, t in self.custom_table.rows()}
        for key, val, kind in data["custom"]:
            key = core._normalize_key(key)
            if key in self.fields:
                _set_editor_value(self.fields[key], val)
            elif rows.get(key, (0, 0, ""))[2] != core.KIND_OTHER:
                rows[key] = (key, val, kind)
        self._restoring = True
        try:
            self.custom_table.set_rows(list(rows.values()), locked_kind=core.KIND_OTHER)
            if data.get("xmp"):  # Belge Okuyucu'dan kaydedilen şablonlar XMP'yi de taşır
                self._set_xmp(data["xmp"])
        finally:
            self._restoring = False
        self._take_snapshot()
        self.tabs.setCurrentIndex(0)
        self.window().statusBar().showMessage(f"Şablon uygulandı: {self.tpl_bar.combo.currentText()}", 5000)

    # ------------------------------------------------------------------ #
    # XMP sekmesi
    # ------------------------------------------------------------------ #
    def _build_xmp_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.xmp_tabs = QTabWidget()
        lay.addWidget(self.xmp_tabs)

        # özellik tablosu
        tw = QWidget()
        tl = QVBoxLayout(tw)
        self.xmp_table = KeyValueTable(["Özellik", "Değer", "Tür"], XMP_KINDS)
        self.xmp_table.edited.connect(self._mark_table_dirty)
        tl.addWidget(self.xmp_table)
        row = QHBoxLayout()
        add = QPushButton("+ Özellik Ekle")
        rem = QPushButton("− Seçili Özelliği Sil")
        sync = QPushButton("Info → XMP Eşitle")
        sync.setToolTip("XMP'yi Belge Bilgileri sekmesindeki değerlerden yeniden oluşturur; Info'da olmayanlar silinir.")
        drop = QPushButton("XMP'yi Tamamen Kaldır")
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        row.addWidget(sync)
        row.addWidget(drop)
        tl.addLayout(row)
        hint = QLabel(
            "Özellik adı önekli yazılır (ör. dc:title, xmp:CreateDate, pdf:Producer, xmpMM:DocumentID). "
            "Liste/Küme değerlerini ';' ile ayırın."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:gray;")
        tl.addWidget(hint)
        self.xmp_tabs.addTab(tw, "Özellikler")

        # ham XML
        self.xmp_raw = QPlainTextEdit()
        self.xmp_raw.setFont(QFont("Consolas", 10))
        self.xmp_raw.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.xmp_raw.textChanged.connect(self._mark_raw_dirty)
        self.xmp_tabs.addTab(self.xmp_raw, "Ham XML")

        self.xmp_tabs.currentChanged.connect(lambda *_: self._sync_xmp())
        add.clicked.connect(self._add_xmp)
        rem.clicked.connect(self.xmp_table.remove_selected)
        sync.clicked.connect(self._info_to_xmp)
        drop.clicked.connect(self._drop_xmp)
        return w

    def _add_xmp(self) -> None:
        r = self.xmp_table.add_row("dc:", "", core.XMP_TEXT)
        self.xmp_table.editItem(self.xmp_table.item(r, 0))
        self._mark_table_dirty()

    def _mark_table_dirty(self) -> None:
        if not self._loading:
            self._xmp_table_dirty = True

    def _mark_raw_dirty(self) -> None:
        if not self._loading:
            self._xmp_raw_dirty = True

    def _set_xmp(self, xml: str) -> None:
        """XMP'yi hem tabloya hem ham editöre yükler."""
        self._loading = True
        try:
            self.xmp_xml = xml or ""
            self.xmp_raw.setPlainText(self.xmp_xml)
            self.xmp_table.clear_rows()
            try:
                for key, val, kind in core.xmp_to_items(self.xmp_xml):
                    self.xmp_table.add_row(key, val, kind, locked=(kind == "yapı"))
            except Exception as exc:  # noqa: BLE001
                self.xmp_table.add_row("<hata>", f"XMP çözümlenemedi: {exc}", core.XMP_TEXT, locked=True)
        finally:
            self._loading = False
            self._xmp_table_dirty = False
            self._xmp_raw_dirty = False

    def _sync_xmp(self) -> bool:
        """Tablo veya ham XML'deki bekleyen değişiklikleri birbirine aktarır."""
        try:
            if self._xmp_table_dirty:
                xml = core.items_to_xmp(self.xmp_xml, self.xmp_table.rows())
                self._set_xmp(xml)
            elif self._xmp_raw_dirty:
                self._set_xmp(self.xmp_raw.toPlainText())
            return True
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "XMP hatası", exc)
            return False

    def _info_to_xmp(self) -> None:
        self._flush_pending()
        if not self._sync_xmp():
            return
        try:
            self._set_xmp(core.info_to_xmp(self.xmp_xml, self.collect_info()))
            self.xmp_tabs.setCurrentIndex(0)
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "XMP hatası", exc)
        self._take_snapshot()

    def _drop_xmp(self) -> None:
        self._flush_pending()
        self._set_xmp("")
        self._take_snapshot()

    # ------------------------------------------------------------------ #
    # Geri al / yinele
    # ------------------------------------------------------------------ #
    def _watch_edits(self) -> None:
        for ed in self.fields.values():
            if isinstance(ed, DateField):
                ed.changed.connect(self._on_edit)
            elif isinstance(ed, QComboBox):
                ed.currentTextChanged.connect(self._on_edit)
            else:
                ed.textChanged.connect(self._on_edit)
        self.custom_table.edited.connect(self._on_edit)
        self.xmp_table.edited.connect(self._on_edit)
        self.xmp_raw.textChanged.connect(self._on_edit)

    def _on_edit(self, *_) -> None:
        if self.doc and not (self._loading or self._restoring):
            self._snap_timer.start()

    def _current_xmp(self) -> str:
        if self._xmp_raw_dirty:
            return self.xmp_raw.toPlainText()
        if self._xmp_table_dirty:
            try:
                return core.items_to_xmp(self.xmp_xml, self.xmp_table.rows())
            except Exception:  # noqa: BLE001 - yarım yazılmış özellik adı vb.
                pass
        return self.xmp_xml

    def _snapshot(self) -> tuple:
        fields = tuple(_editor_value(ed)[0] for ed in self.fields.values())
        return fields, tuple(self.custom_table.rows()), self._current_xmp()

    def _apply_snapshot(self, snap: tuple) -> None:
        fields, custom, xmp = snap
        self._restoring = True
        try:
            for ed, val in zip(self.fields.values(), fields):
                _set_editor_value(ed, val)
            self.custom_table.set_rows(list(custom), locked_kind=core.KIND_OTHER)
            self._set_xmp(xmp)
        finally:
            self._restoring = False

    def _take_snapshot(self) -> None:
        self._snap_timer.stop()
        if not self.doc:
            return
        snap = self._snapshot()
        if self._history and snap == self._history[self._hist_pos]:
            return
        del self._history[self._hist_pos + 1:]
        self._history.append(snap)
        if len(self._history) > HISTORY_LIMIT:
            del self._history[0]
        self._hist_pos = len(self._history) - 1
        self._update_history_buttons()

    def _flush_pending(self) -> None:
        if self._snap_timer.isActive():
            self._take_snapshot()

    def _reset_history(self) -> None:
        self._snap_timer.stop()
        self._initial = self._snapshot()
        self._saved_snap = None
        self._history = [self._initial]
        self._hist_pos = 0
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        self.btn_undo.setEnabled(self._hist_pos > 0)
        self.btn_redo.setEnabled(0 <= self._hist_pos < len(self._history) - 1)
        self.state_changed.emit()

    def _current_snap(self) -> tuple | None:
        return self._history[self._hist_pos] if 0 <= self._hist_pos < len(self._history) else None

    def is_modified(self) -> bool:
        """Ekrandaki değerler dosyadakinden farklı mı?"""
        self._flush_pending()
        return self.doc is not None and self._current_snap() != self._initial

    def needs_save(self) -> bool:
        """Henüz kaydedilmemiş ya da son kayıttan sonra değiştirilmiş mi? (imzalı belgeler hariç)"""
        self._flush_pending()
        if self.doc is None or self.doc.signed_by:
            return False
        return self._saved_snap is None or self._current_snap() != self._saved_snap

    def undo(self) -> None:
        self._flush_pending()
        if self._hist_pos <= 0:
            return
        self._hist_pos -= 1
        self._apply_snapshot(self._history[self._hist_pos])
        self._update_history_buttons()

    def redo(self) -> None:
        self._flush_pending()
        if self._hist_pos >= len(self._history) - 1:
            return
        self._hist_pos += 1
        self._apply_snapshot(self._history[self._hist_pos])
        self._update_history_buttons()

    def revert_to_file(self) -> None:
        if self._initial is None:
            return
        self._flush_pending()
        self._apply_snapshot(self._initial)
        self._take_snapshot()

    # ------------------------------------------------------------------ #
    # Sürükle-bırak
    # ------------------------------------------------------------------ #
    def dragEnterEvent(self, e):
        if _pdf_paths_from_mime(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = _pdf_paths_from_mime(e.mimeData())
        if paths:
            self.load(paths[0])

    # ------------------------------------------------------------------ #
    # Yükleme / kaydetme
    # ------------------------------------------------------------------ #
    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "PDF seç", "", "PDF dosyaları (*.pdf)")
        if path:
            self.load(path)

    def load(self, path: str, password: str = "") -> None:
        while True:
            try:
                doc = core.read_document(path, password)
                break
            except core.PasswordRequired:
                pw = _ask_password(self, path)
                if pw is None:
                    return
                password = pw
            except Exception as exc:  # noqa: BLE001
                _show_error(self, "PDF açılamadı", exc)
                return

        self.doc = doc
        self.password = password
        if doc.signed_by:
            self.path_label.setText(
                f"🔒  {path}\nBu belge dijital olarak imzalanmış ({', '.join(doc.signed_by)}); "
                "değiştirilemez, yalnızca görüntülenebilir."
            )
            self.path_label.setStyleSheet(
                "padding:12px; border:1px solid #e0b252; border-left:4px solid #d48a00;"
                " border-radius:8px; background:#fff8e6; font-weight:600;"
            )
        else:
            self.path_label.setText("📄  " + path)
            self.path_label.setStyleSheet(
                f"padding:12px; border:1px solid {theme.BORDER}; border-left:4px solid {theme.BLUE};"
                f" border-radius:8px; background:white; font-weight:600;"
            )

        # dosya bilgileri
        self.file_table.setRowCount(0)
        for k, v in doc.file_info:
            r = self.file_table.rowCount()
            self.file_table.insertRow(r)
            self.file_table.setItem(r, 0, QTableWidgetItem(k))
            item = QTableWidgetItem(v)
            item.setToolTip(v)
            self.file_table.setItem(r, 1, item)
        self.file_table.resizeRowsToContents()

        # info
        self._restoring = True
        try:
            by_key = {e.key: e for e in doc.info}
            for key, ed in self.fields.items():
                entry = by_key.get(key)
                _set_editor_value(ed, entry.value if entry else "")
            self.custom_table.set_rows(
                [(e.key, e.value, e.kind) for e in doc.info if e.key not in self.fields],
                locked_kind=core.KIND_OTHER,
            )
            self._set_xmp(doc.xmp)
        finally:
            self._restoring = False
        self._reset_history()

        self.tabs.setEnabled(True)
        locked = bool(doc.signed_by)
        for b in (self.btn_save, self.btn_reload, self.btn_clear):
            b.setEnabled(not locked)
        self.btn_diff.setEnabled(True)
        self.window().statusBar().showMessage(f"Yüklendi: {os.path.basename(path)}", 5000)

    def collect_info(self) -> list[core.InfoEntry]:
        out: list[core.InfoEntry] = []
        for key, ed in self.fields.items():
            val, kind = _editor_value(ed)
            if val != "":
                out.append(core.InfoEntry(key, val, kind))
        for key, val, kind in self.custom_table.rows():
            out.append(core.InfoEntry(key, val, kind))
        return out

    def clear_all(self) -> None:
        if QMessageBox.question(
            self,
            "Tüm metadatayı temizle",
            "Tüm Info alanları ve XMP metadata ekranda temizlenecek.\n"
            "Değişiklik, 'Yeni Dosya Olarak Kaydet' ile kaydettiğinizde yeni dosyaya uygulanır. "
            "'Geri Al' ile ekrandaki temizliği iptal edebilirsiniz. Devam edilsin mi?",
        ) != QMessageBox.Yes:
            return
        self._flush_pending()
        for ed in self.fields.values():
            _set_editor_value(ed, "")
        self.custom_table.clear_rows()
        self._set_xmp("")
        self.chk_strip_pages.setChecked(True)
        self.chk_sync.setChecked(False)
        self._take_snapshot()

    # ------------------------------------------------------------------ #
    # Karşılaştırma
    # ------------------------------------------------------------------ #
    def _is_locked(self) -> bool:
        if self.doc and self.doc.signed_by:
            QMessageBox.information(
                self, APP_NAME, "Bu belge dijital olarak imzalanmış; değiştirilip yeniden kaydedilemez."
            )
            return True
        return False

    def _diff_dialog(self, accept_text: str | None) -> DiffDialog | None:
        if not self.doc or not self._sync_xmp():
            return None
        info = self.collect_info()
        rows = diff_rows("Info", _info_rows(self.doc.info), _info_rows(info), label=_field_label)

        notes = []
        new_xml = self.xmp_xml
        if self.chk_sync.isChecked():
            try:
                new_xml = core.info_to_xmp(new_xml, info)
                notes.append("XMP yalnızca Info alanlarından oluşturulacak; Info'da olmayan XMP verileri silinecek.")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Info → XMP yansıtması önizlenemedi: {exc}")
        try:
            rows += diff_rows("XMP", core.xmp_to_items(self.doc.xmp), core.xmp_to_items(new_xml))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"XMP karşılaştırılamadı: {exc}")
        if self.doc.xmp.strip() and not new_xml.strip():
            notes.append("XMP metadata tamamen kaldırılacak.")
        if self.chk_strip_pages.isChecked():
            notes.append("Sayfa düzeyindeki XMP ve PieceInfo verileri de silinecek.")
        if self.lang.note(self.doc.lang):
            notes.insert(0, self.lang.note(self.doc.lang))
        if accept_text and self.sign.note():
            notes.insert(0, self.sign.note())
        return DiffDialog(self, "Değişiklikler: dosyadaki ↔ kaydedilecek", rows, notes, accept_text)

    def show_diff(self) -> None:
        dlg = self._diff_dialog(None)
        if dlg:
            dlg.exec()

    def _show_output(self, path: str) -> None:
        self.out_label.setText(path if len(path) <= 60 else "…" + path[-59:])
        self.out_label.setToolTip(path)

    def _output_name(self) -> str:
        name = os.path.splitext(os.path.basename(self.doc.path))[0]
        if not name.endswith(OUTPUT_SUFFIX):
            name += OUTPUT_SUFFIX
        return name + ".pdf"

    def save(self) -> None:
        """Karşılaştırmayı gösterir; onaylanırsa çıktı klasörüne otomatik kaydeder."""
        if self._is_locked():
            return
        dlg = self._diff_dialog("✔  Onayla ve Kaydet")
        if not dlg or not dlg.exec():
            return
        try:
            folder = self.output.ensure()
        except OSError as exc:
            _show_error(self, "Çıktı klasörü oluşturulamadı", exc)
            return
        self._write(_unique_path(folder, self._output_name()))

    def save_as(self) -> None:
        """Karşılaştırmadan sonra konumu kullanıcıya sorar."""
        if self._is_locked():
            return
        dlg = self._diff_dialog("✔  Onayla ve Konum Seç…")
        if not dlg or not dlg.exec():
            return
        dst, _ = QFileDialog.getSaveFileName(
            self, "Farklı kaydet", os.path.join(self.output.path(), self._output_name()), "PDF dosyaları (*.pdf)"
        )
        if dst:
            self._write(dst)

    def write_file(self, dst: str) -> bool:
        """Ekrandaki değerlerle dst'yi yazar (imzalama açıksa imzalar); hata olursa istisna fırlatır.

        İmzalandıysa True döner.
        """
        self._flush_pending()
        if self.doc.signed_by:
            raise core.SignedDocument("Belge dijital olarak imzalanmış; değiştirilemez.")
        if not self._sync_xmp():
            raise ValueError("XMP verisi geçersiz; XMP sekmesini kontrol edin.")

        def write(path: str) -> None:
            core.save_document(
                self.doc.path,
                path,
                self.collect_info(),
                self.xmp_xml,
                password=self.password,
                sync_xmp=self.chk_sync.isChecked(),
                strip_page_metadata=self.chk_strip_pages.isChecked(),
                lang=self.lang.active(),
            )

        signed = self.sign.write(dst, write, self.password)
        self.saved_path = dst
        self._saved_snap = self._current_snap()
        self.state_changed.emit()
        return signed

    def save_to_output(self) -> tuple[str, bool]:
        """Soru sormadan çıktı klasörüne kaydeder -> (yol, imzalandı mı)."""
        dst = _unique_path(self.output.ensure(), self._output_name())
        return dst, self.write_file(dst)

    def _write(self, dst: str) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            signed = self.write_file(dst)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            _show_error(self, "Kaydedilemedi", exc)
            return
        QApplication.restoreOverrideCursor()
        self.window().statusBar().showMessage(f"Kaydedildi{' ve imzalandı' if signed else ''}: {dst}", 10000)
        if self.embedded:
            # hızlı çalışma: listede ✔ görünür, onay penceresi açılmaz
            return
        text = f"Yeni dosya kaydedildi:\n{dst}"
        if signed:
            text = f"Yeni dosya kaydedildi ve 🔒 '{self.sign.active().label}' imzasıyla imzalandı:\n{dst}"
        box = QMessageBox(QMessageBox.Information, "Kaydedildi", text, parent=self)
        b_open = box.addButton("Kaydedileni Aç", QMessageBox.AcceptRole)
        b_show = box.addButton("Klasörde Göster", QMessageBox.ActionRole)
        box.addButton("Tamam", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_open:
            self.load(dst, self.password)
        elif box.clickedButton() is b_show:
            _reveal_in_explorer(dst)


# =========================================================================== #
# Toplu düzenleme
# =========================================================================== #


class BatchEditor(QWidget):
    def __init__(self, store: TemplateStore, output: OutputFolder, sign: SignChoice, lang: LanguageChoice,
                 parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.output = output
        self.sign = sign
        self.lang = lang
        self._passwords: dict[str, str] = {}
        root = QHBoxLayout(self)

        # --- sol: dosya listesi ---
        left = QGroupBox("Dosyalar (sürükleyip bırakabilirsiniz)")
        ll = QVBoxLayout(left)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        ll.addWidget(self.list)
        row = QHBoxLayout()
        b_add = QPushButton("+ Dosya Ekle")
        b_rem = QPushButton("− Seçileni Çıkar")
        b_clr = QPushButton("Listeyi Temizle")
        row.addWidget(b_add)
        row.addWidget(b_rem)
        row.addWidget(b_clr)
        ll.addLayout(row)
        root.addWidget(left, 2)

        b_add.clicked.connect(self._add_files)
        b_rem.clicked.connect(lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()])
        b_clr.clicked.connect(self.list.clear)

        # --- sağ: alanlar ---
        right = QVBoxLayout()
        root.addLayout(right, 3)

        self.tpl_bar = TemplateBar(
            store, self._template_collect, self._template_apply,
            apply_tip="Şablonu uygular: şablondaki alanlar işaretlenir, diğer alanların işareti kaldırılır.",
        )
        right.addWidget(self.tpl_bar)

        fields_box = QGroupBox("Uygulanacak Alanlar (yalnızca işaretli alanlar değişir; işaretli + boş = alan silinir)")
        form = QFormLayout(fields_box)
        self.fields: dict[str, tuple[QCheckBox, QWidget]] = {}
        for key in core.STANDARD_KEYS:
            chk = QCheckBox()
            ed = _make_field_editor(key)
            if isinstance(ed, DateField):
                ed.changed.connect(lambda c=chk: c.setChecked(True))
            elif isinstance(ed, QComboBox):
                ed.currentTextChanged.connect(lambda *_, c=chk: c.setChecked(True))
            else:
                ed.setClearButtonEnabled(False)
                ed.textEdited.connect(lambda *_, c=chk: c.setChecked(True))
            h = QHBoxLayout()
            h.addWidget(chk)
            h.addWidget(ed, 1)
            form.addRow(f"{core.LABELS[key]}:", h)
            self.fields[key] = (chk, ed)
        right.addWidget(fields_box)

        custom_box = QGroupBox("Özel Alanlar (eklenir/güncellenir; değer boşsa silinir)")
        cl = QVBoxLayout(custom_box)
        self.custom = KeyValueTable(["Anahtar", "Değer", "Tür"], [core.KIND_STRING, core.KIND_NAME])
        cl.addWidget(self.custom)
        h = QHBoxLayout()
        ca = QPushButton("+ Alan Ekle")
        cr = QPushButton("− Seçili Alanı Sil")
        h.addWidget(ca)
        h.addWidget(cr)
        h.addStretch(1)
        cl.addLayout(h)
        ca.clicked.connect(lambda: self.custom.add_row("/YeniAlan", "", core.KIND_STRING))
        cr.clicked.connect(self.custom.remove_selected)
        right.addWidget(custom_box)

        opt_box = QGroupBox("Seçenekler")
        ol = QFormLayout(opt_box)
        self.chk_strip = QCheckBox("Önce tüm metadatayı temizle (Info + XMP + sayfa XMP)")
        self.chk_sync = QCheckBox("XMP'yi yalnızca Info alanlarından oluştur (Info'da olmayanlar silinir)")
        self.chk_xmp = QCheckBox("Şablondaki XMP'yi de yaz (Belge Okuyucu'dan kaydedilen şablonlar)")
        self.chk_xmp.setToolTip("Uygulanan şablon XMP içeriyorsa her dosyanın XMP'si onunla değiştirilir.")
        self.chk_xmp.setEnabled(False)
        self._tpl_xmp = ""
        ol.addRow(self.chk_strip)
        ol.addRow(self.chk_sync)
        ol.addRow(self.chk_xmp)
        out_row = QHBoxLayout()
        self.out_dir = QLineEdit(output.path())
        self.out_dir.setPlaceholderText("Boş = her dosya kendi klasörüne kaydedilir")
        self.out_dir.editingFinished.connect(lambda: output.set_path(self.out_dir.text().strip()))
        output.changed.connect(self.out_dir.setText)
        b_dir = QPushButton("Seç…")
        out_row.addWidget(self.out_dir, 1)
        out_row.addWidget(b_dir)
        ol.addRow("Çıktı klasörü:", out_row)
        self.suffix = QLineEdit(OUTPUT_SUFFIX)
        ol.addRow("Dosya adı eki:", self.suffix)
        right.addWidget(opt_box)
        b_dir.clicked.connect(self._choose_dir)
        self.lang_bar = LangBar(lang)
        right.addWidget(self.lang_bar)
        self.sign_bar = SignBar(sign)
        right.addWidget(self.sign_bar)

        act = QHBoxLayout()
        self.b_preview = QPushButton("🔍  Önizle")
        self.b_preview.setToolTip("Dosyaları kaydetmeden, her dosyada hangi alanın nasıl değişeceğini gösterir.")
        self.b_apply = QPushButton("▶  Uygula ve Yeni Dosyalar Olarak Kaydet")
        self.b_apply.setProperty("primary", True)
        self.b_strip = QPushButton("🧹  Sadece Tüm Metadatayı Temizle")
        act.addWidget(self.b_preview)
        act.addWidget(self.b_apply)
        act.addWidget(self.b_strip)
        right.addLayout(act)
        self.b_preview.clicked.connect(self._preview)
        self.b_apply.clicked.connect(lambda: self._run(strip_only=False))
        self.b_strip.clicked.connect(lambda: self._run(strip_only=True))

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        right.addWidget(self.log)

    # sürükle-bırak
    def dragEnterEvent(self, e):
        if _pdf_paths_from_mime(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._add_paths(_pdf_paths_from_mime(e.mimeData()))

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF seç", "", "PDF dosyaları (*.pdf)")
        self._add_paths(paths)

    def _add_paths(self, paths: list[str]) -> None:
        existing = {self.list.item(i).text() for i in range(self.list.count())}
        for p in paths:
            p = os.path.normpath(p)
            if p not in existing:
                self.list.addItem(p)
                existing.add(p)

    def _choose_dir(self) -> None:
        self.output.choose(self)

    # ------------------------------------------------------------------ #
    # Şablonlar
    # ------------------------------------------------------------------ #
    def _template_collect(self) -> dict:
        fields = {key: _editor_value(ed)[0] for key, (chk, ed) in self.fields.items() if chk.isChecked()}
        data = {"fields": fields, "custom": [list(r) for r in self.custom.rows()]}
        if self._xmp_for_run():
            data["xmp"] = self._tpl_xmp
        return data

    def _xmp_for_run(self) -> str | None:
        return self._tpl_xmp if self.chk_xmp.isChecked() and self._tpl_xmp else None

    def _template_apply(self, data: dict) -> None:
        for key, (chk, ed) in self.fields.items():
            if key in data["fields"]:
                _set_editor_value(ed, data["fields"][key])
                chk.setChecked(True)
            else:
                chk.setChecked(False)
        self.custom.set_rows(
            [(k, v, t) for k, v, t in data["custom"] if t != core.KIND_OTHER]
        )
        self._tpl_xmp = data.get("xmp", "")
        self.chk_xmp.setEnabled(bool(self._tpl_xmp))
        self.chk_xmp.setChecked(bool(self._tpl_xmp))
        self.window().statusBar().showMessage(f"Şablon uygulandı: {self.tpl_bar.combo.currentText()}", 5000)

    # ------------------------------------------------------------------ #
    # İşlem
    # ------------------------------------------------------------------ #
    def _changes(self) -> dict[str, tuple[str, str] | None]:
        changes: dict[str, tuple[str, str] | None] = {}
        for key, (chk, ed) in self.fields.items():
            if not chk.isChecked():
                continue
            val, kind = _editor_value(ed)
            changes[key] = (kind, val) if val != "" else None
        for key, val, kind in self.custom.rows():
            changes[key] = (kind, val) if val != "" else None
        return changes

    def _files(self) -> list[str]:
        files = [self.list.item(i).text() for i in range(self.list.count())]
        if not files:
            QMessageBox.information(self, APP_NAME, "Önce listeye PDF ekleyin.")
        return files

    def _check_changes(self, changes) -> bool:
        if (not changes and not self.chk_strip.isChecked() and not self.chk_sync.isChecked()
                and not self._xmp_for_run() and not self.lang.active()):
            QMessageBox.information(self, APP_NAME, "Değiştirilecek alan seçilmedi.")
            return False
        return True

    def _dst_for(self, src: str) -> str:
        folder = self.out_dir.text().strip() or os.path.dirname(src)
        name, ext = os.path.splitext(os.path.basename(src))
        suffix = self.suffix.text() or OUTPUT_SUFFIX
        if not name.endswith(suffix):
            name += suffix
        return _unique_path(folder, f"{name}{ext}")

    def _with_password(self, src: str, func) -> bool:
        """func(şifre) çağırır; şifre gerekirse sorar ve hatırlar. Atlanırsa False döner."""
        password = self._passwords.get(src, "")
        while True:
            try:
                func(password)
                if password:
                    self._passwords[src] = password
                return True
            except core.PasswordRequired:
                pw = _ask_password(self, src)
                if pw is None:
                    return False
                password = pw

    def _preview(self) -> None:
        files = self._files()
        if not files:
            return
        changes = self._changes()
        if not self._check_changes(changes):
            return

        rows = []
        notes = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for src in files:
                name = os.path.basename(src)
                result = {}

                def run(pw, src=src, result=result):
                    result["v"] = core.preview_batch(src, changes, self.chk_strip.isChecked(), pw)

                try:
                    if not self._with_password(src, run):
                        notes.append(f"{name}: şifre girilmedi, önizlenmedi.")
                        continue
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"{name}: {exc}")
                    continue
                old, new = result["v"]
                file_rows = diff_rows(name, _info_rows(old), _info_rows(new), label=_field_label)
                if not any(r[2] != "aynı" for r in file_rows):
                    notes.append(f"{name}: Info alanlarında değişiklik yok.")
                rows += file_rows
        finally:
            QApplication.restoreOverrideCursor()

        if self.chk_strip.isChecked():
            notes.insert(0, "Önce tüm metadata (XMP ve sayfa XMP dahil) temizlenecek.")
        if self.chk_sync.isChecked():
            notes.insert(0, "XMP yalnızca Info alanlarından yeniden oluşturulacak (önizlemede yalnızca Info gösteriliyor).")
        if self.sign.note():
            notes.insert(0, self.sign.note().replace("Belge", "Her belge", 1))
        if self.lang.note():
            notes.insert(0, self.lang.note().replace("Belge dili", "Her belgenin dili", 1))
        if self._xmp_for_run():
            notes.insert(0, "Her dosyanın XMP'si şablondaki XMP ile değiştirilecek (önizlemede yalnızca Info gösteriliyor).")
        dlg = DiffDialog(self, f"Toplu önizleme ({len(files)} dosya)", rows, notes, "▶  Uygula ve Kaydet")
        if dlg.exec():
            self._run(strip_only=False)

    def _run(self, strip_only: bool) -> None:
        files = self._files()
        if not files:
            return
        changes = {} if strip_only else self._changes()
        if not strip_only and not self._check_changes(changes):
            return
        out = self.out_dir.text().strip()
        if out and not os.path.isdir(out):
            os.makedirs(out, exist_ok=True)

        ok = 0
        self.log.appendPlainText(f"--- {len(files)} dosya işleniyor ---")
        if self.sign.active():
            self.log.appendPlainText(f"🔒 Dijital imza: {self.sign.active().label}")
        for src in files:
            dst = self._dst_for(src)

            def run(pw, src=src, dst=dst):
                def write(path):
                    if strip_only:
                        core.strip_file(src, path, pw, lang=self.lang.active())
                    else:
                        core.apply_batch(
                            src, path, changes,
                            strip_first=self.chk_strip.isChecked(),
                            sync_xmp=self.chk_sync.isChecked(),
                            password=pw,
                            xmp=self._xmp_for_run(),
                            lang=self.lang.active(),
                        )

                self.sign.write(dst, write, pw)

            try:
                if self._with_password(src, run):
                    lock = "🔒 " if self.sign.active() else ""
                    self.log.appendPlainText(f"✔ {lock}{os.path.basename(src)}  →  {dst}")
                    ok += 1
                else:
                    self.log.appendPlainText(f"✖ {os.path.basename(src)}: şifre girilmedi, atlandı")
            except Exception as exc:  # noqa: BLE001
                self.log.appendPlainText(f"✖ {os.path.basename(src)}: {exc}")
            QApplication.processEvents()
        self.log.appendPlainText(f"--- Bitti: {ok}/{len(files)} başarılı ---")


# =========================================================================== #
# Ana pencere
# =========================================================================== #


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setWindowIcon(theme.app_icon())
        self.store = TemplateStore()
        self.output = OutputFolder(self)
        self.sign = SignChoice(signing.SignatureStore(), self)
        self.lang = LanguageChoice(self)
        self.single = SingleEditor(self.store, self.output, self.sign, self.lang)
        self.batch = BatchEditor(self.store, self.output, self.sign, self.lang)
        self.signatures = SignaturePanel(self.sign)
        self.multi = MultiEditor(self._make_embedded_editor, self.output)
        self.compress = CompressPanel(self.output)
        self.reader = ReaderPanel(self.store)
        # bir sekmede kaydedilen/silinen şablon diğerlerinde de görünsün
        self.single.tpl_bar.store_changed.connect(self._refresh_templates)
        self.batch.tpl_bar.store_changed.connect(self._refresh_templates)
        self.multi.templates_changed.connect(self._refresh_templates)
        self.reader.templates_changed.connect(self._refresh_templates)
        self.reader.open_requested.connect(self._open_in_single)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.addTab(self.single, "Tek Dosya Düzenle")
        self.tabs.addTab(self.batch, "Toplu Düzenleme")
        self.tabs.addTab(self.multi, "Online Düzenleme")
        self.tabs.addTab(self.compress, "PDF Küçült")
        self.tabs.addTab(self.reader, "Belge Okuyucu")
        self.tabs.addTab(self.signatures, "Dijital İmza")
        for bar in (self.single.sign_bar, self.batch.sign_bar):
            bar.manage_requested.connect(self._show_signatures)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._build_header())
        body = QVBoxLayout()
        body.setContentsMargins(12, 8, 12, 8)
        body.addWidget(self.tabs)
        cl.addLayout(body, 1)
        self.setCentralWidget(central)
        self.statusBar()

        menu = self.menuBar().addMenu("&Dosya")
        a_open = QAction("PDF Aç…", self, shortcut=QKeySequence.Open, triggered=self._open)
        a_save = QAction("Kaydet (çıktı klasörüne)", self, shortcut=QKeySequence.Save,
                         triggered=lambda: self._on_editor("save"))
        a_save_as = QAction("Farklı Kaydet…", self, shortcut=QKeySequence("Ctrl+Shift+S"),
                            triggered=lambda: self._on_editor("save_as"))
        a_out = QAction("Çıktı Klasörünü Aç", self, triggered=self.output.open)
        a_out_set = QAction("Çıktı Klasörünü Değiştir…", self, triggered=lambda: self.output.choose(self))
        a_quit = QAction("Çıkış", self, shortcut=QKeySequence.Quit, triggered=self.close)
        menu.addAction(a_open)
        menu.addAction(a_save)
        menu.addAction(a_save_as)
        menu.addSeparator()
        menu.addAction(a_out)
        menu.addAction(a_out_set)
        menu.addSeparator()
        menu.addAction(a_quit)

        # metin kutusunda imleç varken Ctrl+Z o kutunun kendi geri alma işlemini yapar
        edit_menu = self.menuBar().addMenu("&Düzen")
        edit_menu.addAction(QAction("Geri Al", self, shortcut=QKeySequence.Undo,
                                    triggered=lambda: self._on_editor("undo")))
        edit_menu.addAction(QAction("Yinele", self, shortcut=QKeySequence("Ctrl+Y"),
                                    triggered=lambda: self._on_editor("redo")))
        edit_menu.addSeparator()
        edit_menu.addAction(QAction("Değişiklikleri Göster…", self, shortcut=QKeySequence("Ctrl+D"),
                                    triggered=lambda: self._on_editor("show_diff")))

        help_menu = self.menuBar().addMenu("&Yardım")
        help_menu.addAction(QAction("Hakkında", self, triggered=lambda: QMessageBox.about(
            self, APP_NAME,
            f"<b>{APP_NAME}</b><br>{theme.BRAND_NAME}<br><br>"
            f"PDF Info sözlüğü ve XMP metadata görüntüleme / düzenleme aracı."
            f"<br><br>Şablon dosyası:<br>{self.store.path}"
            f"<br><br>Çıktı klasörü:<br>{self.output.path()}"
            f"<br><br>Dijital imzalar:<br>{self.sign.store.folder}",
        )))

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(16, 10, 16, 10)
        logo = QLabel()
        pm = QPixmap(theme.asset_path("logo.png"))
        if not pm.isNull():
            logo.setPixmap(pm.scaledToHeight(44, Qt.SmoothTransformation))
        lay.addWidget(logo)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("HeaderTitle")
        sub = QLabel(theme.BRAND_NAME.upper())
        sub.setObjectName("HeaderSub")
        credit = QLabel(f"designed by {theme.DESIGNER}")
        credit.setObjectName("HeaderCredit")
        sub_row = QHBoxLayout()
        sub_row.setSpacing(10)
        sub_row.addWidget(sub, 0, Qt.AlignVCenter)
        sub_row.addWidget(credit, 0, Qt.AlignVCenter)
        sub_row.addStretch(1)
        texts.addWidget(title)
        texts.addLayout(sub_row)
        lay.addSpacing(6)
        lay.addLayout(texts)
        lay.addStretch(1)
        return header

    def _make_embedded_editor(self) -> SingleEditor:
        editor = SingleEditor(self.store, self.output, self.sign, self.lang, embedded=True)
        editor.sign_bar.manage_requested.connect(self._show_signatures)
        return editor

    def _open_in_single(self, path: str, password: str) -> None:
        self.single.load(path, password)
        self.tabs.setCurrentWidget(self.single)

    def _show_signatures(self) -> None:
        self.tabs.setCurrentWidget(self.signatures)

    def _refresh_templates(self) -> None:
        self.single.tpl_bar.refresh()
        self.batch.tpl_bar.refresh()
        self.multi.refresh_templates()

    def _open(self) -> None:
        if self.tabs.currentWidget() is self.multi:
            self.multi._choose_files()
        elif self.tabs.currentWidget() is self.compress:
            self.compress._choose()
        elif self.tabs.currentWidget() is self.reader:
            self.reader._choose()
        else:
            self.single.choose_file()

    def _on_editor(self, method: str) -> None:
        """Kısayolu açık sekmedeki düzenleyiciye iletir (Tek Dosya veya Online Düzenleme)."""
        current = self.tabs.currentWidget()
        editor = self.single if current is self.single else (
            self.multi.current_editor() if current is self.multi else None
        )
        if editor is not None and editor.doc is not None:
            getattr(editor, method)()

    def closeEvent(self, e) -> None:
        if self.multi.has_unsaved() and QMessageBox.question(
            self, APP_NAME,
            "Online Düzenleme sekmesinde kaydedilmemiş değişiklikler var.\nYine de çıkılsın mı?",
        ) != QMessageBox.Yes:
            e.ignore()
            return
        super().closeEvent(e)
