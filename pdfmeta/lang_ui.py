"""Kaydederken belge dilini (/Lang + XMP dc:language) sabit bir değere ayarlama seçeneği."""
from __future__ import annotations

import re

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QWidget

LANGUAGES = [
    ("en-US", "İngilizce (ABD)"),
    ("en-GB", "İngilizce (Birleşik Krallık)"),
    ("tr-TR", "Türkçe"),
    ("de-DE", "Almanca"),
    ("fr-FR", "Fransızca"),
    ("es-ES", "İspanyolca"),
    ("it-IT", "İtalyanca"),
    ("nl-NL", "Felemenkçe"),
    ("ar-SA", "Arapça"),
    ("ru-RU", "Rusça"),
    ("zh-CN", "Çince (basitleştirilmiş)"),
]
_TAG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def valid_tag(tag: str) -> bool:
    return bool(_TAG_RE.match(tag.strip()))


class LanguageChoice(QObject):
    """Kalıcı ayar; Tek Dosya, Toplu ve Online Düzenleme sekmeleri paylaşır."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("SuspendGlobal", "PDFMetadataDuzenleyici")
        self._enabled = self._settings.value("lang_enabled", False, type=bool)
        self._value = str(self._settings.value("lang_value", "en-US") or "en-US")

    def enabled(self) -> bool:
        return self._enabled

    def value(self) -> str:
        return self._value

    def set_enabled(self, on: bool) -> None:
        if on != self._enabled:
            self._enabled = on
            self._settings.setValue("lang_enabled", on)
            self.changed.emit()

    def set_value(self, tag: str) -> None:
        tag = tag.strip()
        if valid_tag(tag) and tag != self._value:
            self._value = tag
            self._settings.setValue("lang_value", tag)
            self.changed.emit()

    def active(self) -> str | None:
        """Ayar açıksa uygulanacak dil etiketi, değilse None."""
        return self._value if self._enabled and valid_tag(self._value) else None

    def note(self, current: str | None = None) -> str | None:
        tag = self.active()
        if not tag:
            return None
        if current is not None and current == tag:
            return f"🌐 Belge dili zaten {tag}."
        before = f"{current or 'belirtilmemiş'} → " if current is not None else ""
        return f"🌐 Belge dili {before}{tag} olarak ayarlanacak (/Lang ve XMP dc:language)."


class LangBar(QWidget):
    """[🌐 Belge dilini her zaman ayarla] [en-US ▼]"""

    def __init__(self, choice: LanguageChoice, parent=None):
        super().__init__(parent)
        self.choice = choice
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.chk = QCheckBox("🌐  Kaydederken belge dilini her zaman şuna ayarla:")
        self.chk.setToolTip(
            "İşaretliyken kaydedilen her belgenin dili (/Lang ve XMP dc:language) seçilen değere ayarlanır.\n"
            "Seçim hatırlanır; Tek Dosya, Toplu ve Online Düzenleme sekmelerinde geçerlidir."
        )
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setMinimumWidth(240)
        for tag, name in LANGUAGES:
            self.combo.addItem(f"{tag}  —  {name}", tag)
        self.hint = QLabel()
        self.hint.setStyleSheet("color:#b3261e;")
        lay.addWidget(self.chk)
        lay.addWidget(self.combo)
        lay.addWidget(self.hint)
        lay.addStretch(1)
        self.chk.toggled.connect(choice.set_enabled)
        self.combo.currentIndexChanged.connect(self._on_pick)
        self.combo.lineEdit().editingFinished.connect(self._on_edit)
        choice.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        for w in (self.chk, self.combo):
            w.blockSignals(True)
        try:
            self.chk.setChecked(self.choice.enabled())
            tag = self.choice.value()
            idx = self.combo.findData(tag)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
            else:
                self.combo.setEditText(tag)
            self.combo.setEnabled(self.choice.enabled())
            self.hint.clear()
        finally:
            for w in (self.chk, self.combo):
                w.blockSignals(False)

    def _on_pick(self, idx: int) -> None:
        tag = self.combo.itemData(idx)
        if tag:
            self.choice.set_value(tag)

    def _on_edit(self) -> None:
        text = self.combo.currentText().split("—")[0].strip()
        if valid_tag(text):
            self.hint.clear()
            self.choice.set_value(text)
        else:
            self.hint.setText("Geçersiz dil kodu (ör. en-US)")
