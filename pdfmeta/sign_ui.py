"""Dijital imza arayüzü: imza yönetim sekmesi ve kaydetme ekranlarındaki 'İmzala' çubuğu."""
from __future__ import annotations

import os
import re
import traceback

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import signing, theme


def _error(parent, title: str, exc: Exception) -> None:
    box = QMessageBox(QMessageBox.Critical, title, str(exc) or exc.__class__.__name__, parent=parent)
    box.setDetailedText(traceback.format_exc())
    box.exec()


class SignChoice(QObject):
    """Kaydederken kullanılacak imza seçimi (kalıcı); tek dosya ve toplu sekme bunu paylaşır."""

    changed = Signal()

    def __init__(self, store: signing.SignatureStore, parent=None):
        super().__init__(parent)
        self.store = store
        self._settings = QSettings("SuspendGlobal", "PDFMetadataDuzenleyici")
        self._enabled = self._settings.value("sign_enabled", False, type=bool)
        self._id = str(self._settings.value("sign_id", "") or "")
        self._visible = self._settings.value("sign_visible", True, type=bool)
        if not store.get(self._id):
            items = store.all()
            self._id = items[0].id if items else ""

    def enabled(self) -> bool:
        return self._enabled

    def sig_id(self) -> str:
        return self._id

    def visible(self) -> bool:
        return self._visible

    def _set(self, key: str, attr: str, value) -> None:
        if getattr(self, attr) != value:
            setattr(self, attr, value)
            self._settings.setValue(key, value)
            self.changed.emit()

    def set_enabled(self, on: bool) -> None:
        self._set("sign_enabled", "_enabled", bool(on))

    def set_id(self, sig_id: str) -> None:
        self._set("sign_id", "_id", sig_id or "")

    def set_visible(self, on: bool) -> None:
        self._set("sign_visible", "_visible", bool(on))

    def store_changed(self) -> None:
        """İmza eklenip silindiğinde seçimi geçerli tutar."""
        if not self.store.get(self._id):
            items = self.store.all()
            self.set_id(items[0].id if items else "")
            if not items:
                self.set_enabled(False)
        self.changed.emit()

    def active(self) -> signing.SignatureProfile | None:
        """İmzalama açıksa seçili imza, değilse None."""
        return self.store.get(self._id) if self._enabled else None

    def note(self) -> str | None:
        p = self.active()
        if p is None:
            return None
        return f"🔒 Belge '{p.label}' dijital imzasıyla imzalanacak; imzalandıktan sonra değiştirilemez."

    def write(self, dst: str, write, password: str = "") -> bool:
        """write(yol) ile dosyayı oluşturur; imzalama açıksa sonucu imzalayıp dst'ye yazar.

        İmzalandıysa True döner.
        """
        p = self.active()
        if p is None:
            write(dst)
            return False
        tmp = dst + ".imzasiz.tmp"
        try:
            write(tmp)
            signing.sign_file(self.store, p.id, tmp, dst, password, self._visible)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True


class SignBar(QWidget):
    """Kaydetme ekranlarının altındaki çubuk: [İmzala] [imza seçimi] [görünür imza kutusu]."""

    manage_requested = Signal()

    def __init__(self, choice: SignChoice, parent=None):
        super().__init__(parent)
        self.choice = choice
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        self.chk = QCheckBox("🔒  İmzala")
        self.chk.setToolTip(
            "İşaretliyken kaydedilen her belge seçili dijital imzayla imzalanır ve sonradan değiştirilemez.\n"
            "Seçim hatırlanır; her belge için yeniden seçmeniz gerekmez."
        )
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        self.chk_visible = QCheckBox("Son sayfada görünür imza kutusu")
        self.chk_visible.setToolTip("Son sayfanın sağ alt köşesine imzalayan, şirket ve tarih bilgisini içeren kutu ekler.")
        b_manage = QPushButton("İmzaları Yönet…")
        lay.addWidget(self.chk)
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.chk_visible)
        lay.addWidget(b_manage)

        self.chk.toggled.connect(self._on_toggle)
        self.combo.currentIndexChanged.connect(self._on_combo)
        self.chk_visible.toggled.connect(choice.set_visible)
        b_manage.clicked.connect(self.manage_requested)
        choice.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        items = self.choice.store.all()
        for w in (self.chk, self.combo, self.chk_visible):
            w.blockSignals(True)
        try:
            self.combo.clear()
            for p in items:
                self.combo.addItem(p.label, p.id)
            if not items:
                self.combo.setPlaceholderText("(henüz dijital imza yok — İmzaları Yönet…)")
            idx = self.combo.findData(self.choice.sig_id())
            self.combo.setCurrentIndex(idx if idx >= 0 else (0 if items else -1))
            self.chk.setChecked(self.choice.enabled() and bool(items))
            self.chk_visible.setChecked(self.choice.visible())
            on = self.chk.isChecked()
            self.combo.setEnabled(bool(items))
            self.chk_visible.setEnabled(on)
            self.setStyleSheet(
                f"SignBar {{ background:#e3f3fc; border:1px solid {theme.BLUE}; border-radius:6px; }}" if on else ""
            )
        finally:
            for w in (self.chk, self.combo, self.chk_visible):
                w.blockSignals(False)

    def _on_toggle(self, on: bool) -> None:
        if on and not self.choice.store.all():
            QMessageBox.information(
                self, "Dijital imza", "Önce 'Dijital İmza' sekmesinden şirketiniz için bir dijital imza oluşturun."
            )
            self.chk.setChecked(False)
            self.manage_requested.emit()
            return
        if on and self.combo.currentData():
            self.choice.set_id(self.combo.currentData())
        self.choice.set_enabled(on)

    def _on_combo(self, _idx: int) -> None:
        if self.combo.currentData():
            self.choice.set_id(self.combo.currentData())


class SignaturePanel(QWidget):
    """Dijital İmza sekmesi: şirket imzalarını oluşturma, içe aktarma, silme."""

    def __init__(self, choice: SignChoice, parent=None):
        super().__init__(parent)
        self.choice = choice
        self.store = choice.store
        root = QHBoxLayout(self)

        # --- sol: kayıtlı imzalar ---
        left = QGroupBox("Kayıtlı Dijital İmzalar")
        ll = QVBoxLayout(left)
        self.list = QListWidget()
        ll.addWidget(self.list, 1)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details.setStyleSheet(
            f"background:#f7f9fb; border:1px solid {theme.BORDER}; border-radius:6px; padding:8px; font-weight:400;"
        )
        ll.addWidget(self.details)
        row = QHBoxLayout()
        self.b_use = QPushButton("✔  Kaydederken Bu İmzayı Kullan")
        self.b_use.setProperty("primary", True)
        self.b_use.setToolTip("Bu imzayı seçer ve alt çubuktaki 'İmzala' kutusunu işaretler.")
        self.b_export = QPushButton("Sertifikayı Dışa Aktar (.cer)…")
        self.b_export.setToolTip(
            "Belgeyi alanlar bu sertifikayı Adobe Reader'da güvenilir kimliklere ekleyerek imzanızı doğrulayabilir."
        )
        self.b_edit = QPushButton("Düzenle…")
        self.b_edit.setToolTip("Unvan, konum ve imza nedenini değiştirir (sertifika aynı kalır).")
        self.b_del = QPushButton("Sil")
        row.addWidget(self.b_use)
        row.addWidget(self.b_export)
        row.addWidget(self.b_edit)
        row.addWidget(self.b_del)
        ll.addLayout(row)
        root.addWidget(left, 3)

        self.list.currentItemChanged.connect(self._show_details)
        self.b_use.clicked.connect(self._use)
        self.b_export.clicked.connect(self._export)
        self.b_edit.clicked.connect(self._edit)
        self.b_del.clicked.connect(self._delete)

        # --- sağ: yeni imza ---
        right = QVBoxLayout()
        root.addLayout(right, 2)
        new_box = QGroupBox("Yeni Dijital İmza Oluştur")
        form = QFormLayout(new_box)
        self.e_company = QLineEdit()
        self.e_company.setPlaceholderText("ör. Suspend Global Ltd. Şti.")
        self.e_signer = QLineEdit()
        self.e_signer.setPlaceholderText("İmzayı atan kişinin adı soyadı")
        self.e_title = QLineEdit()
        self.e_title.setPlaceholderText("ör. Genel Müdür")
        self.e_email = QLineEdit()
        self.e_location = QLineEdit()
        self.e_location.setPlaceholderText("ör. İstanbul")
        self.e_country = QLineEdit("TR")
        self.e_country.setMaxLength(2)
        self.e_country.setMaximumWidth(60)
        self.e_reason = QLineEdit("Belge onayı")
        self.e_years = QSpinBox()
        self.e_years.setRange(1, 30)
        self.e_years.setValue(5)
        self.e_years.setSuffix(" yıl")
        form.addRow("Şirket adı *:", self.e_company)
        form.addRow("İmzalayan kişi *:", self.e_signer)
        form.addRow("Unvan:", self.e_title)
        form.addRow("E-posta:", self.e_email)
        form.addRow("Konum (şehir):", self.e_location)
        form.addRow("Ülke kodu:", self.e_country)
        form.addRow("İmza nedeni:", self.e_reason)
        form.addRow("Geçerlilik süresi:", self.e_years)
        b_create = QPushButton("＋  Dijital İmza Oluştur")
        b_create.setProperty("primary", True)
        form.addRow(b_create)
        right.addWidget(new_box)
        b_create.clicked.connect(self._create)

        imp_box = QGroupBox("Hazır Sertifika")
        il = QVBoxLayout(imp_box)
        lbl = QLabel(
            "Bir sertifika sağlayıcısından aldığınız .pfx / .p12 dosyanız varsa içe aktarabilirsiniz; "
            "bu durumda imzanız alıcılarda doğrudan güvenilir görünür."
        )
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{theme.MUTED}; font-weight:400;")
        b_import = QPushButton("📥  .pfx / .p12 İçe Aktar…")
        il.addWidget(lbl)
        il.addWidget(b_import)
        right.addWidget(imp_box)
        b_import.clicked.connect(self._import)

        info = QLabel(
            "<b>Nasıl çalışır?</b><br>"
            "• Her şirket için bir kez imza oluşturun.<br>"
            "• <i>Tek Dosya Düzenle</i> veya <i>Toplu Düzenleme</i> sekmesinin altındaki <b>🔒 İmzala</b> "
            "kutusunu işaretleyip imzayı seçin; seçim hatırlanır ve kaydedilen <b>her belge</b> otomatik imzalanır.<br>"
            "• İmzalı belge <b>değiştirilemez</b>: bu program imzalı belgeyi düzenlemeye izin vermez, "
            "başka bir programla yapılan her değişiklik de PDF okuyucularında imzayı geçersiz gösterir.<br>"
            "• Burada üretilen sertifikalar kendinden imzalıdır; alıcı, dışa aktardığınız .cer dosyasını "
            "güvenilir listesine eklemezse Adobe Reader 'kimlik doğrulanamadı' uyarısı gösterebilir."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet(
            f"background:white; border:1px solid {theme.BORDER}; border-left:4px solid {theme.BLUE};"
            f" border-radius:8px; padding:10px;"
        )
        right.addWidget(info)
        right.addStretch(1)

        choice.changed.connect(self._mark_selected)
        self.refresh()

    # ------------------------------------------------------------------ #
    def refresh(self, select: str | None = None) -> None:
        current = select or (self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None)
        self.list.clear()
        for p in self.store.all():
            item = QListWidgetItem(p.label)
            item.setData(Qt.UserRole, p.id)
            self.list.addItem(item)
            if p.id == current:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._mark_selected()
        self._show_details()

    def _mark_selected(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            p = self.store.get(item.data(Qt.UserRole))
            if p is None:
                continue
            used = p.id == self.choice.sig_id()
            mark = ("  🔒 (kaydederken kullanılıyor)" if self.choice.enabled() else "  (seçili)") if used else ""
            item.setText(p.label + mark)
            f = item.font()
            f.setBold(used)
            item.setFont(f)

    def _selected(self) -> signing.SignatureProfile | None:
        item = self.list.currentItem()
        return self.store.get(item.data(Qt.UserRole)) if item else None

    def _show_details(self, *_) -> None:
        p = self._selected()
        for b in (self.b_use, self.b_export, self.b_edit, self.b_del):
            b.setEnabled(p is not None)
        if p is None:
            self.details.setText("Henüz dijital imza yok. Sağdaki formdan şirketiniz için bir imza oluşturun.")
            return
        rows = [
            ("Şirket", p.company),
            ("İmzalayan", p.signer),
            ("Unvan", p.title),
            ("E-posta", p.email),
            ("Konum", p.location),
            ("İmza nedeni", p.reason),
            ("Oluşturulma", p.created),
            ("Geçerlilik sonu", p.valid_until),
            ("Tür", "İçe aktarılan sertifika" if p.imported else "Kendinden imzalı sertifika"),
            ("SHA-256 parmak izi", p.fingerprint),
        ]
        self.details.setText(
            "<table>" + "".join(
                f"<tr><td style='color:{theme.MUTED}; padding-right:10px'>{k}</td><td>{v}</td></tr>"
                for k, v in rows if v
            ) + "</table>"
        )

    def _changed(self, select: str | None = None) -> None:
        self.choice.store_changed()
        self.refresh(select)

    # ------------------------------------------------------------------ #
    def _create(self) -> None:
        company, signer = self.e_company.text().strip(), self.e_signer.text().strip()
        if not company or not signer:
            QMessageBox.information(self, "Dijital imza", "Şirket adı ve imzalayan kişi alanları zorunludur.")
            return
        email = self.e_email.text().strip()
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            QMessageBox.information(self, "Dijital imza", "E-posta adresi geçerli görünmüyor.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            p = self.store.create(
                company, signer,
                title=self.e_title.text(), email=email, location=self.e_location.text(),
                country=self.e_country.text(), reason=self.e_reason.text(), years=self.e_years.value(),
            )
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            _error(self, "İmza oluşturulamadı", exc)
            return
        QApplication.restoreOverrideCursor()
        for e in (self.e_company, self.e_signer, self.e_title, self.e_email):
            e.clear()
        if not self.choice.store.get(self.choice.sig_id()):
            self.choice.set_id(p.id)
        self._changed(p.id)
        self._offer_use(p, f"'{p.label}' dijital imzası oluşturuldu.")

    def _offer_use(self, p: signing.SignatureProfile, text: str) -> None:
        box = QMessageBox(QMessageBox.Information, "Dijital imza", text, parent=self)
        b_use = box.addButton("Kaydederken Bu İmzayı Kullan", QMessageBox.AcceptRole)
        box.addButton("Kapat", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_use:
            self.choice.set_id(p.id)
            self.choice.set_enabled(True)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Sertifika seç", "", "Sertifika (*.pfx *.p12)")
        if not path:
            return
        pw, ok = QInputDialog.getText(self, "Sertifika şifresi", "Sertifika dosyasının şifresi:", QLineEdit.Password)
        if not ok:
            return
        company, ok = QInputDialog.getText(
            self, "Şirket", "Bu imza hangi şirket için? (boş = sertifikadaki kurum adı)", text=self.e_company.text()
        )
        if not ok:
            return
        try:
            p = self.store.import_p12(path, pw, company, reason=self.e_reason.text())
        except Exception as exc:  # noqa: BLE001
            _error(self, "Sertifika içe aktarılamadı", exc)
            return
        self._changed(p.id)
        self._offer_use(p, f"'{p.label}' sertifikası içe aktarıldı.")

    def _use(self) -> None:
        p = self._selected()
        if p:
            self.choice.set_id(p.id)
            self.choice.set_enabled(True)
            self.window().statusBar().showMessage(f"Kaydedilen belgeler '{p.label}' imzasıyla imzalanacak.", 6000)

    def _export(self) -> None:
        p = self._selected()
        if not p:
            return
        safe = re.sub(r'[\\/:*?"<>|]+', "_", p.label)
        dst, _ = QFileDialog.getSaveFileName(self, "Sertifikayı dışa aktar", f"{safe}.cer", "Sertifika (*.cer)")
        if not dst:
            return
        try:
            self.store.export_certificate(p.id, dst)
        except Exception as exc:  # noqa: BLE001
            _error(self, "Dışa aktarılamadı", exc)
            return
        self.window().statusBar().showMessage(f"Sertifika kaydedildi: {dst}", 8000)

    def _edit(self) -> None:
        p = self._selected()
        if not p:
            return
        for attr, label in (("title", "Unvan"), ("location", "Konum (şehir)"), ("reason", "İmza nedeni")):
            val, ok = QInputDialog.getText(self, "İmzayı düzenle", f"{label}:", text=getattr(p, attr))
            if not ok:
                return
            setattr(p, attr, val.strip())
        try:
            self.store.update(p)
        except OSError as exc:
            _error(self, "Kaydedilemedi", exc)
            return
        self._changed(p.id)

    def _delete(self) -> None:
        p = self._selected()
        if not p or QMessageBox.question(
            self, "Dijital imza",
            f"'{p.label}' imzası silinsin mi?\n\nÖzel anahtar kalıcı olarak silinir; bu imzayla daha önce "
            "imzalanmış belgeler geçerli kalır ama aynı imzayla yeni belge imzalanamaz.",
        ) != QMessageBox.Yes:
            return
        try:
            self.store.delete(p.id)
        except OSError as exc:
            _error(self, "Silinemedi", exc)
            return
        self._changed()
