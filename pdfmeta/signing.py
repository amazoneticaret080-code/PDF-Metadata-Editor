"""Dijital imza motoru (arayüzden bağımsız).

- Her şirket için kendinden imzalı (self-signed) bir sertifika + özel anahtar üretilir ve
  PKCS#12 (.p12) dosyası olarak %APPDATA%\\PDFMetadataDuzenleyici\\imzalar klasöründe saklanır.
  Hazır bir .pfx/.p12 (ör. bir sertifika sağlayıcısından alınmış) da içe aktarılabilir.
- .p12 şifresi Windows DPAPI ile yalnızca bu kullanıcı hesabının çözebileceği şekilde saklanır;
  böylece her imzalamada şifre sorulmaz.
- Belgeler PAdES "sertifikasyon" imzasıyla (DocMDP: değişikliğe izin yok) imzalanır: imzadan sonra
  yapılan her değişiklik PDF okuyucularında imzayı geçersiz gösterir.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import os
import secrets
import sys
import uuid
from dataclasses import asdict, dataclass

import pikepdf
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, ObjectIdentifier

SIG_FIELD_PREFIX = "Signature"
DOCUMENT_SIGNING_OID = ObjectIdentifier("1.3.6.1.4.1.311.10.3.12")  # Microsoft "Belge İmzalama"
STAMP_W, STAMP_H, STAMP_MARGIN = 230, 70, 36  # pt


def default_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PDFMetadataDuzenleyici", "imzalar")


# --------------------------------------------------------------------------- #
# Şifre saklama (Windows DPAPI)
# --------------------------------------------------------------------------- #


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    inp = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    crypt32 = ctypes.windll.crypt32
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    args = (ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
    if protect:
        args = (ctypes.byref(inp), "PDFMetadataDuzenleyici", None, None, None, 0, ctypes.byref(out))
    if not func(*args):
        raise OSError("İmza şifresi çözülemedi (farklı bir Windows kullanıcısı olabilir).")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _protect(secret: bytes) -> str:
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(secret, True)).decode()
    return "plain:" + base64.b64encode(secret).decode()


def _unprotect(stored: str) -> bytes:
    kind, _, b64 = stored.partition(":")
    raw = base64.b64decode(b64)
    return _dpapi(raw, False) if kind == "dpapi" else raw


# --------------------------------------------------------------------------- #
# İmza kayıtları
# --------------------------------------------------------------------------- #


@dataclass
class SignatureProfile:
    id: str
    company: str
    signer: str
    title: str = ""
    email: str = ""
    location: str = ""
    reason: str = ""
    created: str = ""
    valid_until: str = ""
    fingerprint: str = ""
    imported: bool = False
    secret: str = ""  # DPAPI ile korunan .p12 şifresi

    @property
    def label(self) -> str:
        return f"{self.company} — {self.signer}"


def _name(company: str, signer: str, email: str, location: str, country: str) -> x509.Name:
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, signer), x509.NameAttribute(NameOID.ORGANIZATION_NAME, company)]
    if location:
        attrs.append(x509.NameAttribute(NameOID.LOCALITY_NAME, location))
    if country and len(country) == 2:
        attrs.append(x509.NameAttribute(NameOID.COUNTRY_NAME, country.upper()))
    if email:
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    return x509.Name(attrs)


def _fingerprint(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex(":").upper()


class SignatureStore:
    def __init__(self, folder: str | None = None):
        self.folder = folder or default_dir()
        self.index_path = os.path.join(self.folder, "imzalar.json")
        self._items: dict[str, SignatureProfile] = self._load()

    def _load(self) -> dict[str, SignatureProfile]:
        try:
            with open(self.index_path, encoding="utf-8") as fh:
                raw = json.load(fh)
            fields = SignatureProfile.__dataclass_fields__
            items = [SignatureProfile(**{k: v for k, v in d.items() if k in fields}) for d in raw.get("signatures", [])]
            return {p.id: p for p in items if os.path.exists(self.p12_path(p.id))}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _write(self) -> None:
        os.makedirs(self.folder, exist_ok=True)
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "signatures": [asdict(p) for p in self._items.values()]},
                      fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.index_path)

    def p12_path(self, sig_id: str) -> str:
        return os.path.join(self.folder, f"{sig_id}.p12")

    def all(self) -> list[SignatureProfile]:
        return sorted(self._items.values(), key=lambda p: p.label.casefold())

    def get(self, sig_id: str) -> SignatureProfile | None:
        return self._items.get(sig_id)

    def _add(self, profile: SignatureProfile, p12: bytes) -> SignatureProfile:
        os.makedirs(self.folder, exist_ok=True)
        with open(self.p12_path(profile.id), "wb") as fh:
            fh.write(p12)
        self._items[profile.id] = profile
        self._write()
        return profile

    def create(
        self,
        company: str,
        signer: str,
        title: str = "",
        email: str = "",
        location: str = "",
        country: str = "TR",
        reason: str = "",
        years: int = 5,
    ) -> SignatureProfile:
        """Yeni anahtar çifti ve kendinden imzalı sertifika üretir."""
        company, signer = company.strip(), signer.strip()
        if not company or not signer:
            raise ValueError("Şirket adı ve imzalayan kişi zorunludur.")
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        subject = _name(company, signer, email.strip(), location.strip(), country.strip())
        now = dt.datetime.now(dt.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=365 * max(1, years)))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, content_commitment=True, key_encipherment=False,
                    data_encipherment=False, key_agreement=False, key_cert_sign=False,
                    crl_sign=False, encipher_only=False, decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([DOCUMENT_SIGNING_OID, ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256())
        )
        password = secrets.token_urlsafe(24).encode()
        p12 = pkcs12.serialize_key_and_certificates(
            f"{company} - {signer}".encode(), key, cert, None,
            serialization.BestAvailableEncryption(password),
        )
        profile = SignatureProfile(
            id=uuid.uuid4().hex,
            company=company,
            signer=signer,
            title=title.strip(),
            email=email.strip(),
            location=location.strip(),
            reason=reason.strip(),
            created=now.astimezone().strftime("%d.%m.%Y %H:%M"),
            valid_until=cert.not_valid_after_utc.astimezone().strftime("%d.%m.%Y"),
            fingerprint=_fingerprint(cert),
            secret=_protect(password),
        )
        return self._add(profile, p12)

    def import_p12(
        self, path: str, password: str, company: str, title: str = "", location: str = "", reason: str = ""
    ) -> SignatureProfile:
        """Hazır bir .pfx/.p12 sertifikasını içe aktarır."""
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            key, cert, _ = pkcs12.load_key_and_certificates(data, password.encode() or None)
        except ValueError as exc:
            raise ValueError("Sertifika açılamadı: şifre yanlış veya dosya geçersiz.") from exc
        if key is None or cert is None:
            raise ValueError("Dosyada özel anahtar veya sertifika bulunamadı.")
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        org = cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
        mail = cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)
        profile = SignatureProfile(
            id=uuid.uuid4().hex,
            company=company.strip() or (org[0].value if org else "") or "İçe aktarılan",
            signer=cn[0].value if cn else os.path.basename(path),
            title=title.strip(),
            email=mail[0].value if mail else "",
            location=location.strip(),
            reason=reason.strip(),
            created=dt.datetime.now().strftime("%d.%m.%Y %H:%M"),
            valid_until=cert.not_valid_after_utc.astimezone().strftime("%d.%m.%Y"),
            fingerprint=_fingerprint(cert),
            imported=True,
            secret=_protect(password.encode()),
        )
        return self._add(profile, data)

    def update(self, profile: SignatureProfile) -> None:
        if profile.id in self._items:
            self._items[profile.id] = profile
            self._write()

    def delete(self, sig_id: str) -> None:
        if self._items.pop(sig_id, None) is not None:
            try:
                os.remove(self.p12_path(sig_id))
            except OSError:
                pass
            self._write()

    def certificate(self, sig_id: str) -> x509.Certificate:
        p = self._items[sig_id]
        with open(self.p12_path(sig_id), "rb") as fh:
            _, cert, _ = pkcs12.load_key_and_certificates(fh.read(), _unprotect(p.secret) or None)
        return cert

    def export_certificate(self, sig_id: str, dst: str) -> None:
        """Alıcıların güvenilir listesine ekleyebilmesi için açık sertifikayı (.cer) yazar."""
        with open(dst, "wb") as fh:
            fh.write(self.certificate(sig_id).public_bytes(serialization.Encoding.DER))

    def signer(self, sig_id: str):
        from pyhanko.sign import signers

        p = self._items[sig_id]
        s = signers.SimpleSigner.load_pkcs12(self.p12_path(sig_id), passphrase=_unprotect(p.secret) or None)
        if s is None:
            raise ValueError(f"'{p.label}' imzasının anahtarı yüklenemedi.")
        return s


# --------------------------------------------------------------------------- #
# İmza durumu ve imzalama
# --------------------------------------------------------------------------- #


def _sig_fields(fields, depth=0):
    for f in fields:
        if depth > 20:
            return
        if "/Kids" in f:
            yield from _sig_fields(f.Kids, depth + 1)
        if f.get("/FT") == pikepdf.Name.Sig and "/V" in f:
            yield f


def signatures_in(pdf: pikepdf.Pdf) -> list[str]:
    """Belgedeki dolu imza alanlarının imzalayan adlarını döndürür (imzasızsa boş liste)."""
    names: list[str] = []
    try:
        acro = pdf.Root.get("/AcroForm")
        if acro is not None and "/Fields" in acro:
            for f in _sig_fields(acro.Fields):
                v = f.V
                names.append(str(v.get("/Name", "")) or str(f.get("/T", "imza")))
        if not names and "/Perms" in pdf.Root and "/DocMDP" in pdf.Root.Perms:
            names.append("sertifikalı belge")
    except Exception:  # noqa: BLE001
        pass
    return names


def _next_field_name(pdf_path: str, password: str) -> tuple[str, int, list[float] | None]:
    with pikepdf.open(pdf_path, password=password) as pdf:
        used = set()
        acro = pdf.Root.get("/AcroForm")
        if acro is not None and "/Fields" in acro:
            used = {str(f.get("/T", "")) for f in acro.Fields}
        n = 1
        while f"{SIG_FIELD_PREFIX}{n}" in used:
            n += 1
        box = [float(x) for x in pdf.pages[-1].mediabox] if len(pdf.pages) else None
        return f"{SIG_FIELD_PREFIX}{n}", len(pdf.pages), box


def _stamp_style(profile: SignatureProfile):
    from pyhanko import stamp
    from pyhanko.pdf_utils import text

    lines = [f"Dijital olarak imzalandı: {profile.signer}"]
    if profile.title:
        lines.append(profile.title)
    lines.append(profile.company)
    lines.append("Tarih: %(ts)s")
    box = text.TextBoxStyle(font_size=8)
    font = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf")
    if os.path.exists(font):
        try:
            from pyhanko.pdf_utils.font.opentype import GlyphAccumulatorFactory

            logging.getLogger("fontTools").setLevel(logging.ERROR)  # alt küme uyarıları

            box = text.TextBoxStyle(font=GlyphAccumulatorFactory(font), font_size=8)
        except ImportError:  # fontTools yoksa standart yazı tipine düş
            pass
    return stamp.TextStampStyle(
        stamp_text="\n".join(lines),
        text_box_style=box,
        border_width=1,
        timestamp_format="%d.%m.%Y %H:%M:%S %z",
    )


def _metadata_preserving_writer(inf):
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    class Writer(IncrementalPdfFileWriter):
        # pyHanko yazarken /ModDate'i şimdiki zamana çeker ve /Producer'a kendi adını ekler
        # (Info ve XMP). Kullanıcının ayarladığı metadata aynen kalsın diye bu adım atlanır.
        def _update_meta(self):
            pass

    return Writer(inf, strict=False)


def sign_file(
    store: SignatureStore,
    sig_id: str,
    src: str,
    dst: str,
    password: str = "",
    visible: bool = False,
) -> None:
    """src'yi imzalayıp dst'ye yazar. Sertifikasyon imzası: sonradan değişikliğe izin verilmez."""
    from pyhanko.sign import fields, signers

    profile = store.get(sig_id)
    if profile is None:
        raise ValueError("Seçili dijital imza bulunamadı; Dijital İmza sekmesinden yeniden seçin.")
    with pikepdf.open(src, password=password) as pdf:
        if signatures_in(pdf):
            raise ValueError("Belge zaten dijital olarak imzalanmış; tekrar imzalanamaz.")
    field_name, n_pages, box = _next_field_name(src, password)
    signer = store.signer(sig_id)

    meta = signers.PdfSignatureMetadata(
        field_name=field_name,
        certify=True,
        docmdp_permissions=fields.MDPPerm.NO_CHANGES,
        subfilter=fields.SigSeedSubFilter.PADES,
        md_algorithm="sha256",
        reason=profile.reason or None,
        location=profile.location or None,
        name=profile.signer,
        contact_info=profile.email or None,
    )
    with open(src, "rb") as inf:
        w = _metadata_preserving_writer(inf)
        if w.prev.encrypted:
            w.encrypt(password)
        stamp_style = None
        if visible and box:
            # son sayfanın sağ alt köşesi
            x2 = box[2] - STAMP_MARGIN
            y1 = box[1] + STAMP_MARGIN
            spec = fields.SigFieldSpec(
                field_name, on_page=n_pages - 1, box=(int(x2 - STAMP_W), int(y1), int(x2), int(y1 + STAMP_H))
            )
            stamp_style = _stamp_style(profile)
        else:
            spec = fields.SigFieldSpec(field_name)
        fields.append_signature_field(w, spec)
        pdf_signer = signers.PdfSigner(meta, signer, stamp_style=stamp_style)
        with open(dst, "wb") as outf:
            pdf_signer.sign_pdf(w, output=outf)
