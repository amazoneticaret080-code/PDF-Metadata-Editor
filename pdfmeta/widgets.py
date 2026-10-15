"""Ortak arayüz bileşenleri."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import core
from .templates import TemplateStore

# "Yok" = saat dilimi bilgisi yazılmaz, "Z" = UTC
TZ_CHOICES = ["Yok", "Z"] + [
    f"{'+' if m >= 0 else '-'}{abs(m) // 60:02d}:{abs(m) % 60:02d}"
    for m in range(-12 * 60, 14 * 60 + 1, 30)
]


class DateField(QWidget):
    """PDF tarih alanı: takvim + saat dilimi + ham PDF metni (birbirine senkron)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.edit = QDateTimeEdit()
        self.edit.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
        self.edit.setCalendarPopup(True)
        self.tz = QComboBox()
        self.tz.addItems(TZ_CHOICES)
        self.tz.setToolTip("Saat dilimi")
        self.raw = QLineEdit()
        self.raw.setPlaceholderText("boş = alan yok")
        self.raw.setToolTip("Ham PDF tarih metni (ör. D:20261015143000+03'00'). Boş bırakılırsa alan silinir.")
        now_btn = QPushButton("Şimdi")
        clear_btn = QPushButton("Temizle")

        lay.addWidget(self.edit, 3)
        lay.addWidget(self.tz, 1)
        lay.addWidget(self.raw, 3)
        lay.addWidget(now_btn)
        lay.addWidget(clear_btn)

        self.edit.dateTimeChanged.connect(self._from_widgets)
        self.tz.currentIndexChanged.connect(self._from_widgets)
        self.raw.textChanged.connect(self._from_raw)
        now_btn.clicked.connect(self.set_now)
        clear_btn.clicked.connect(lambda: self.set_raw(""))
        self._update_enabled()

    # ----- dış API -----
    def set_raw(self, raw: str) -> None:
        self.raw.setText(raw or "")

    def get_raw(self) -> str:
        return self.raw.text().strip()

    def set_now(self) -> None:
        now = dt.datetime.now().astimezone()
        self.raw.setText(core.format_pdf_date(now.replace(microsecond=0)))

    # ----- iç senkronizasyon -----
    def _update_enabled(self) -> None:
        has = bool(self.raw.text().strip())
        self.edit.setStyleSheet("" if has else "color: gray;")

    def _from_raw(self, text: str) -> None:
        if self._busy:
            return
        parsed = core.parse_pdf_date(text)
        self._busy = True
        try:
            if parsed:
                naive = parsed.replace(tzinfo=None)
                self.edit.setDateTime(QDateTime(naive.date(), naive.time()))
                off = parsed.utcoffset()
                if off is None:
                    self.tz.setCurrentIndex(0)
                elif off == dt.timedelta(0) and "Z" in text.upper():
                    self.tz.setCurrentIndex(1)
                else:
                    mins = int(off.total_seconds() // 60)
                    label = f"{'+' if mins >= 0 else '-'}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"
                    idx = self.tz.findText(label)
                    if idx < 0:
                        self.tz.addItem(label)
                        idx = self.tz.count() - 1
                    self.tz.setCurrentIndex(idx)
            self.raw.setStyleSheet("" if parsed or not text.strip() else "background:#ffe0e0;")
        finally:
            self._busy = False
        self._update_enabled()
        self.changed.emit()

    def _from_widgets(self, *_):
        if self._busy:
            return
        qdt = self.edit.dateTime()
        d, t = qdt.date(), qdt.time()
        value = dt.datetime(d.year(), d.month(), d.day(), t.hour(), t.minute(), t.second())
        tz_text = self.tz.currentText()
        if tz_text == "Z":
            value = value.replace(tzinfo=dt.timezone.utc)
        elif tz_text != "Yok":
            sign = 1 if tz_text[0] == "+" else -1
            hh, mm = tz_text[1:].split(":")
            value = value.replace(tzinfo=dt.timezone(sign * dt.timedelta(hours=int(hh), minutes=int(mm))))
        self._busy = True
        try:
            self.raw.setText(core.format_pdf_date(value))
            self.raw.setStyleSheet("")
        finally:
            self._busy = False
        self._update_enabled()
        self.changed.emit()


class KeyValueTable(QTableWidget):
    """Anahtar / Değer / Tür sütunlu düzenlenebilir tablo."""

    edited = Signal()

    def __init__(self, headers: list[str], kinds: list[str], parent=None):
        super().__init__(0, len(headers), parent)
        self.kinds = kinds
        self.setHorizontalHeaderLabels(headers)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        if len(headers) > 2:
            hh.setSectionResizeMode(2, QHeaderView.Fixed)
            self.setColumnWidth(2, 120)
        self.setColumnWidth(0, 220)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.itemChanged.connect(lambda *_: self.edited.emit())

    def add_row(self, key: str = "", value: str = "", kind: str | None = None, locked: bool = False) -> int:
        self.blockSignals(True)
        try:
            row = self.rowCount()
            self.insertRow(row)
            k = QTableWidgetItem(key)
            v = QTableWidgetItem(value)
            if locked:
                for it in (k, v):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    it.setForeground(Qt.gray)
            self.setItem(row, 0, k)
            self.setItem(row, 1, v)
            if self.columnCount() > 2:
                combo = QComboBox()
                combo.addItems(self.kinds)
                if kind and combo.findText(kind) < 0:
                    combo.addItem(kind)
                combo.setCurrentText(kind or self.kinds[0])
                combo.setEnabled(not locked)
                combo.currentIndexChanged.connect(lambda *_: self.edited.emit())
                self.setCellWidget(row, 2, combo)
            return row
        finally:
            self.blockSignals(False)

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.removeRow(r)
        if rows:
            self.edited.emit()

    def clear_rows(self) -> None:
        self.setRowCount(0)

    def rows(self) -> list[tuple[str, str, str]]:
        out = []
        for r in range(self.rowCount()):
            key = (self.item(r, 0).text() if self.item(r, 0) else "").strip()
            val = self.item(r, 1).text() if self.item(r, 1) else ""
            kind = self.cellWidget(r, 2).currentText() if self.columnCount() > 2 else self.kinds[0]
            if key:
                out.append((key, val, kind))
        return out

    def set_rows(self, rows: list[tuple[str, str, str]], locked_kind: str | None = None) -> None:
        self.clear_rows()
        for key, val, kind in rows:
            self.add_row(key, val, kind, locked=(kind == locked_kind))


# --------------------------------------------------------------------------- #
# Şablon çubuğu
# --------------------------------------------------------------------------- #


class TemplateBar(QWidget):
    """Şablon seçme / uygulama / kaydetme / silme çubuğu.

    collect() -> şablon sözlüğü, apply(şablon) -> None; ikisi de çağıran sekmeye aittir.
    """

    store_changed = Signal()

    def __init__(self, store: TemplateStore, collect, apply, apply_tip: str = "", parent=None):
        super().__init__(parent)
        self.store = store
        self._collect = collect
        self._apply = apply
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Şablon:"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(200)
        self.combo.setPlaceholderText("(kayıtlı şablon yok)")
        b_apply = QPushButton("Uygula")
        b_apply.setToolTip(apply_tip)
        b_save = QPushButton("Şablon Olarak Kaydet…")
        b_save.setToolTip("Şu anki alan değerlerini ad vererek şablon olarak saklar.")
        b_del = QPushButton("Sil")
        lay.addWidget(self.combo, 1)
        lay.addWidget(b_apply)
        lay.addWidget(b_save)
        lay.addWidget(b_del)
        self._needs_selection = (b_apply, b_del)
        b_apply.clicked.connect(self._on_apply)
        b_save.clicked.connect(self._on_save)
        b_del.clicked.connect(self._on_delete)
        self.refresh()

    def refresh(self, select: str | None = None) -> None:
        current = select or self.combo.currentText()
        self.combo.clear()
        self.combo.addItems(self.store.names())
        idx = self.combo.findText(current)
        self.combo.setCurrentIndex(idx if idx >= 0 else (0 if self.combo.count() else -1))
        for b in self._needs_selection:
            b.setEnabled(self.combo.count() > 0)

    def _on_apply(self) -> None:
        data = self.store.get(self.combo.currentText())
        if data is not None:
            self._apply(data)

    def _on_save(self) -> None:
        data = self._collect()
        if not data["fields"] and not data["custom"]:
            QMessageBox.information(self, "Şablon", "Şablona kaydedilecek dolu alan yok.")
            return
        name, ok = QInputDialog.getText(self, "Şablon olarak kaydet", "Şablon adı:", text=self.combo.currentText())
        name = name.strip()
        if not ok or not name:
            return
        if name in self.store.names() and QMessageBox.question(
            self, "Şablon", f"'{name}' şablonu zaten var. Üzerine yazılsın mı?"
        ) != QMessageBox.Yes:
            return
        try:
            self.store.put(name, data)
        except OSError as exc:
            QMessageBox.critical(self, "Şablon kaydedilemedi", str(exc))
            return
        self.refresh(select=name)
        self.store_changed.emit()

    def _on_delete(self) -> None:
        name = self.combo.currentText()
        if not name or QMessageBox.question(self, "Şablon", f"'{name}' şablonu silinsin mi?") != QMessageBox.Yes:
            return
        try:
            self.store.delete(name)
        except OSError as exc:
            QMessageBox.critical(self, "Şablon silinemedi", str(exc))
            return
        self.refresh()
        self.store_changed.emit()


# --------------------------------------------------------------------------- #
# Karşılaştırma penceresi
# --------------------------------------------------------------------------- #

DIFF_SAME = "aynı"
DIFF_CHANGED = "değişti"
DIFF_ADDED = "eklendi"
DIFF_REMOVED = "silindi"

# yarı saydam renkler: açık ve koyu temada okunur kalır
_DIFF_COLORS = {
    DIFF_CHANGED: QColor(255, 190, 0, 70),
    DIFF_ADDED: QColor(0, 180, 0, 60),
    DIFF_REMOVED: QColor(230, 0, 0, 55),
}


def diff_rows(group: str, old: list[tuple[str, str, str]], new: list[tuple[str, str, str]], label=None):
    """(anahtar, değer, tür) listelerini karşılaştırır -> (bölüm, alan, durum, eski, yeni) satırları."""
    old_d = {k: (v, t) for k, v, t in old}
    new_d = {k: (v, t) for k, v, t in new}
    keys = list(dict.fromkeys([k for k, _, _ in old] + [k for k, _, _ in new]))
    out = []
    for k in keys:
        o, n = old_d.get(k), new_d.get(k)
        if o is None:
            status = DIFF_ADDED
        elif n is None:
            status = DIFF_REMOVED
        else:
            status = DIFF_SAME if o == n else DIFF_CHANGED

        def text(pair):
            if pair is None:
                return ""
            # yalnızca tür değiştiyse bunu görünür kıl
            if o and n and o[0] == n[0] and o[1] != n[1]:
                return f"{pair[0]}  [{pair[1]}]"
            return pair[0]

        out.append((group, label(k) if label else k, status, text(o), text(n)))
    return out


class DiffDialog(QDialog):
    """Eski / yeni metadata değerlerini yan yana gösterir."""

    def __init__(self, parent, title: str, rows, notes: list[str] = (), accept_text: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1000, 600)
        self._rows = rows
        lay = QVBoxLayout(self)

        n = sum(1 for r in rows if r[2] != DIFF_SAME)
        summary = QLabel(f"<b>{n} değişiklik</b>" if n else "<b>Metadata değişikliği yok.</b>")
        lay.addWidget(summary)
        for note in notes:
            lbl = QLabel("• " + note)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:gray;")
            lay.addWidget(lbl)

        self.chk_all = QCheckBox("Değişmeyen alanları da göster")
        self.chk_all.toggled.connect(self._fill)
        lay.addWidget(self.chk_all)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Bölüm", "Alan", "Durum", "Eski Değer", "Yeni Değer"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(2, 80)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setColumnHidden(0, len({r[0] for r in rows}) <= 1)
        lay.addWidget(self.table, 1)

        if accept_text:
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Ok).setText(accept_text)
            buttons.button(QDialogButtonBox.Cancel).setText("İptal")
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.button(QDialogButtonBox.Close).setText("Kapat")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.chk_all.setChecked(n == 0)
        self._fill()

    def _fill(self, *_):
        show_all = self.chk_all.isChecked()
        self.table.setRowCount(0)
        for row in self._rows:
            if row[2] == DIFF_SAME and not show_all:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            color = _DIFF_COLORS.get(row[2])
            for c, val in enumerate(row):
                item = QTableWidgetItem(val)
                item.setToolTip(val)
                if color is not None:
                    item.setBackground(color)
                self.table.setItem(r, c, item)
        self.table.resizeRowsToContents()
