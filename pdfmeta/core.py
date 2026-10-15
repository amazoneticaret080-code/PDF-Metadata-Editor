"""PDF metadata okuma / yazma motoru (pikepdf tabanlı).

Arayüzden bağımsızdır; hem tek dosya düzenleyici hem de toplu işlem bu modülü kullanır.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import warnings
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Name, Pdf, String

from .signing import signatures_in

# --------------------------------------------------------------------------- #
# Sabitler
# --------------------------------------------------------------------------- #

STANDARD_KEYS = [
    "/Title",
    "/Author",
    "/Subject",
    "/Keywords",
    "/Creator",
    "/Producer",
    "/CreationDate",
    "/ModDate",
    "/Trapped",
]
DATE_KEYS = {"/CreationDate", "/ModDate"}
NAME_KEYS = {"/Trapped"}

LABELS = {
    "/Title": "Başlık",
    "/Author": "Yazar",
    "/Subject": "Konu",
    "/Keywords": "Anahtar Kelimeler",
    "/Creator": "Oluşturan Uygulama",
    "/Producer": "PDF Üretici",
    "/CreationDate": "Oluşturma Tarihi",
    "/ModDate": "Değiştirme Tarihi",
    "/Trapped": "Trapped",
}

KIND_STRING = "metin"
KIND_NAME = "isim"
KIND_OTHER = "diğer"


# --------------------------------------------------------------------------- #
# Tarih dönüşümleri
# --------------------------------------------------------------------------- #

_DATE_RE = re.compile(
    r"^(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
    r"(?:([Zz+\-])(?:(\d{2})'?(?:(\d{2})'?)?)?)?"
)


def parse_pdf_date(raw: str) -> dt.datetime | None:
    """'D:20261015143000+03'00'' biçimini datetime'a çevirir (çözülemezse None)."""
    s = (raw or "").strip()
    if s.startswith("D:"):
        s = s[2:]
    m = _DATE_RE.match(s)
    if not m:
        return None
    tz = None
    sign = m.group(7)
    if sign in ("Z", "z"):
        tz = dt.timezone.utc
    elif sign:
        off = dt.timedelta(hours=int(m.group(8) or 0), minutes=int(m.group(9) or 0))
        tz = dt.timezone(off if sign == "+" else -off)
    try:
        return dt.datetime(
            int(m.group(1)),
            int(m.group(2) or 1),
            int(m.group(3) or 1),
            int(m.group(4) or 0),
            int(m.group(5) or 0),
            int(m.group(6) or 0),
            tzinfo=tz,
        )
    except ValueError:
        return None


def format_pdf_date(value: dt.datetime) -> str:
    """datetime'ı PDF tarih metnine çevirir: D:YYYYMMDDHHmmSS+HH'mm'."""
    s = value.strftime("D:%Y%m%d%H%M%S")
    off = value.utcoffset()
    if off is None:
        return s
    total = int(off.total_seconds())
    if total == 0:
        return s + "Z"
    sign = "+" if total > 0 else "-"
    total = abs(total)
    return f"{s}{sign}{total // 3600:02d}'{(total % 3600) // 60:02d}'"


# --------------------------------------------------------------------------- #
# Veri modelleri
# --------------------------------------------------------------------------- #


@dataclass
class InfoEntry:
    key: str  # "/Title" gibi
    value: str  # metin olarak gösterim
    kind: str  # KIND_STRING / KIND_NAME / KIND_OTHER


@dataclass
class DocumentData:
    path: str
    info: list[InfoEntry] = field(default_factory=list)
    xmp: str = ""  # ham XMP XML (yoksa boş)
    signed_by: list[str] = field(default_factory=list)  # doluysa belge dijital imzalıdır
    lang: str = ""  # belge dili (/Lang), ör. "tr-TR"
    file_info: list[tuple[str, str]] = field(default_factory=list)


class PasswordRequired(Exception):
    pass


# --------------------------------------------------------------------------- #
# Okuma
# --------------------------------------------------------------------------- #


def _open(path: str, password: str = "") -> Pdf:
    try:
        return Pdf.open(path, password=password)
    except pikepdf.PasswordError as exc:
        raise PasswordRequired(str(exc)) from exc


def _obj_to_entry(key: str, obj) -> InfoEntry:
    if isinstance(obj, String):
        return InfoEntry(key, str(obj), KIND_STRING)
    if isinstance(obj, Name):
        return InfoEntry(key, str(obj)[1:], KIND_NAME)
    try:
        text = repr(obj)
    except Exception:  # noqa: BLE001
        text = "<okunamadı>"
    return InfoEntry(key, text, KIND_OTHER)


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{n} B"


def _file_info(path: str, pdf: Pdf) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    st = os.stat(path)
    rows.append(("Dosya adı", os.path.basename(path)))
    rows.append(("Klasör", os.path.dirname(path)))
    rows.append(("Dosya boyutu", f"{_human_size(st.st_size)} ({st.st_size:,} bayt)".replace(",", ".")))
    rows.append(("Sistem: oluşturulma", dt.datetime.fromtimestamp(st.st_ctime).strftime("%d.%m.%Y %H:%M:%S")))
    rows.append(("Sistem: değiştirilme", dt.datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M:%S")))
    rows.append(("PDF sürümü", pdf.pdf_version + (f" (ext. {pdf.extension_level})" if pdf.extension_level else "")))
    rows.append(("Sayfa sayısı", str(len(pdf.pages))))

    if len(pdf.pages):
        box = pdf.pages[0].mediabox
        w = float(box[2]) - float(box[0])
        h = float(box[3]) - float(box[1])
        rows.append(("1. sayfa boyutu", f"{w * 25.4 / 72:.1f} × {h * 25.4 / 72:.1f} mm ({w:.0f} × {h:.0f} pt)"))

    rows.append(("Şifreli", "Evet" if pdf.is_encrypted else "Hayır"))
    if pdf.is_encrypted:
        try:
            enc = pdf.encryption
            rows.append(("Şifreleme", f"R{enc.R} / V{enc.V}, {enc.bits} bit, {enc.stream_method}"))
        except Exception:  # noqa: BLE001
            pass
    rows.append(("Linearized (web için)", "Evet" if pdf.is_linearized else "Hayır"))
    rows.append(("Form (AcroForm)", "Var" if "/AcroForm" in pdf.Root else "Yok"))
    try:
        rows.append(("Ekli dosya sayısı", str(len(pdf.attachments))))
    except Exception:  # noqa: BLE001
        pass
    rows.append(("Nesne sayısı", str(len(pdf.objects))))
    rows.append(("Belge dili (Lang)", str(pdf.Root.get("/Lang", "")) or "Belirtilmemiş"))
    rows.append(("XMP metadata", "Var" if "/Metadata" in pdf.Root else "Yok"))
    rows.append(("Info sözlüğü", "Var" if "/Info" in pdf.trailer else "Yok"))

    page_meta = sum(1 for p in pdf.pages if "/Metadata" in p.obj)
    if page_meta:
        rows.append(("Sayfa düzeyi XMP", f"{page_meta} sayfada"))

    if "/ID" in pdf.trailer:
        ids = [bytes(x).hex().upper() for x in pdf.trailer.ID]
        for i, val in enumerate(ids):
            rows.append((f"Belge ID [{i}]", val))

    try:
        with open(path, "rb") as fh:
            revisions = fh.read().count(b"%%EOF")
        rows.append(("Kayıt revizyonu (%%EOF)", str(revisions)))
    except OSError:
        pass
    return rows


def read_document(path: str, password: str = "") -> DocumentData:
    with _open(path, password) as pdf:
        data = DocumentData(path=path)
        if "/Info" in pdf.trailer:
            for key, obj in pdf.trailer.Info.items():
                data.info.append(_obj_to_entry(str(key), obj))
        if "/Metadata" in pdf.Root:
            raw = pdf.Root.Metadata.read_bytes()
            data.xmp = raw.decode("utf-8", errors="replace")
        data.signed_by = signatures_in(pdf)
        data.lang = str(pdf.Root.get("/Lang", ""))
        data.file_info = _file_info(path, pdf)
        if data.signed_by:
            data.file_info.insert(7, ("Dijital imza", "🔒 " + ", ".join(data.signed_by)))
        return data


# --------------------------------------------------------------------------- #
# Yazma
# --------------------------------------------------------------------------- #


def strip_all_metadata(pdf: Pdf) -> None:
    """Info sözlüğü, belge/sayfa XMP'leri ve PieceInfo verilerini kaldırır."""
    if "/Info" in pdf.trailer:
        del pdf.trailer["/Info"]
    for key in ("/Metadata", "/PieceInfo"):
        if key in pdf.Root:
            del pdf.Root[key]
    for page in pdf.pages:
        for key in ("/Metadata", "/PieceInfo"):
            if key in page.obj:
                del page.obj[key]


def _make_value(pdf: Pdf, kind: str, value: str, old_obj=None):
    if kind == KIND_NAME:
        return Name("/" + value.lstrip("/"))
    if kind == KIND_OTHER and old_obj is not None:
        return old_obj
    return String(value)


def _normalize_key(key: str) -> str:
    key = key.strip()
    return key if key.startswith("/") else "/" + key


def set_xmp(pdf: Pdf, xml: str | None) -> None:
    if not xml or not xml.strip():
        if "/Metadata" in pdf.Root:
            del pdf.Root["/Metadata"]
        return
    pdf.Root.Metadata = pdf.make_stream(
        xml.encode("utf-8"), Type=Name.Metadata, Subtype=Name.XML
    )


def sync_docinfo_to_xmp(pdf: Pdf) -> None:
    """XMP'yi yalnızca Info sözlüğündeki standart alanlardan yeniden oluşturur.

    Eski XMP'deki diğer her şey (ör. Info'da olmayan pdf:Keywords) silinir; Info'da
    XMP karşılığı olan alan yoksa XMP tamamen kaldırılır.
    """
    if "/Metadata" in pdf.Root:
        del pdf.Root["/Metadata"]
    if "/Info" not in pdf.trailer:
        return
    # XMP karşılığı olmayan özel alanlar için pikepdf uyarı verir; bunlar zaten Info'da kalır.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
            meta.load_from_docinfo(pdf.docinfo)
            empty = not len(list(meta.keys()))
    if empty and "/Metadata" in pdf.Root:
        del pdf.Root["/Metadata"]


class SignedDocument(Exception):
    pass


def _check_unsigned(pdf: Pdf) -> None:
    names = signatures_in(pdf)
    if names:
        raise SignedDocument(f"Belge dijital olarak imzalanmış ({', '.join(names)}); değiştirilemez.")


def set_language(pdf: Pdf, lang: str) -> None:
    """Belge dilini hem katalogda (/Lang) hem XMP'de (dc:language) ayarlar."""
    lang = lang.strip()
    if not lang:
        return
    pdf.Root.Lang = String(lang)
    if "/Metadata" in pdf.Root:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
                meta["dc:language"] = {lang}


def _check_paths(src: str, dst: str) -> None:
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
        raise ValueError("Kaynak dosyanın üzerine yazılamaz; lütfen farklı bir dosya adı seçin.")


def _save(pdf: Pdf, dst: str) -> None:
    # fix_metadata_version=False: kullanıcının XMP'ye yazdığı değerleri değiştirmemek için
    # encryption=True: kaynak şifreliyse aynı şifreleme ayarları korunur
    pdf.save(dst, fix_metadata_version=False, encryption=bool(pdf.is_encrypted))


def save_document(
    src: str,
    dst: str,
    info: list[InfoEntry],
    xmp: str | None,
    password: str = "",
    sync_xmp: bool = False,
    strip_page_metadata: bool = False,
    lang: str | None = None,
) -> None:
    """Tek dosya düzenleyicinin kaydetme işlemi: Info + XMP tamamen verilenle değiştirilir.

    lang verilirse belge dili (/Lang ve XMP dc:language) ona ayarlanır.
    """
    _check_paths(src, dst)
    with _open(src, password) as pdf:
        _check_unsigned(pdf)
        old = dict(pdf.trailer.Info.items()) if "/Info" in pdf.trailer else {}
        if strip_page_metadata:
            strip_all_metadata(pdf)
        elif "/Info" in pdf.trailer:
            del pdf.trailer["/Info"]

        new_info = pikepdf.Dictionary()
        for entry in info:
            key = _normalize_key(entry.key)
            if key == "/":
                continue
            new_info[key] = _make_value(pdf, entry.kind, entry.value, old.get(key))
        if len(new_info):
            pdf.trailer.Info = pdf.make_indirect(new_info)

        set_xmp(pdf, xmp)
        if sync_xmp:
            sync_docinfo_to_xmp(pdf)
        if lang:
            set_language(pdf, lang)
        _save(pdf, dst)


def apply_batch(
    src: str,
    dst: str,
    changes: dict[str, tuple[str, str] | None],
    strip_first: bool = False,
    sync_xmp: bool = False,
    password: str = "",
    xmp: str | None = None,
    lang: str | None = None,
) -> None:
    """Toplu işlem: yalnızca verilen anahtarlar değişir. Değer None ise anahtar silinir.

    xmp verilirse belgenin XMP'si onunla değiştirilir (sync_xmp açıksa ardından Info'dan yeniden oluşturulur).
    """
    _check_paths(src, dst)
    with _open(src, password) as pdf:
        _check_unsigned(pdf)
        _apply_changes(pdf, changes, strip_first)
        if xmp:
            set_xmp(pdf, xmp)
        if sync_xmp:
            sync_docinfo_to_xmp(pdf)
        if lang:
            set_language(pdf, lang)
        _save(pdf, dst)


def _apply_changes(pdf: Pdf, changes: dict[str, tuple[str, str] | None], strip_first: bool) -> None:
    if strip_first:
        strip_all_metadata(pdf)
    if changes:
        info = pdf.docinfo  # yoksa oluşturur
        for raw_key, val in changes.items():
            key = _normalize_key(raw_key)
            if val is None or val[1] == "":
                if key in info:
                    del info[key]
            else:
                info[key] = _make_value(pdf, val[0], val[1])
        if not len(info):
            del pdf.trailer["/Info"]


def _info_entries(pdf: Pdf) -> list[InfoEntry]:
    if "/Info" not in pdf.trailer:
        return []
    return [_obj_to_entry(str(k), v) for k, v in pdf.trailer.Info.items()]


def preview_batch(
    src: str,
    changes: dict[str, tuple[str, str] | None],
    strip_first: bool = False,
    password: str = "",
) -> tuple[list[InfoEntry], list[InfoEntry]]:
    """Toplu işlemi dosyayı kaydetmeden bellekte uygular; (eski Info, yeni Info) döndürür."""
    with _open(src, password) as pdf:
        old = _info_entries(pdf)
        _apply_changes(pdf, changes, strip_first)
        return old, _info_entries(pdf)


def strip_file(src: str, dst: str, password: str = "", lang: str | None = None) -> None:
    _check_paths(src, dst)
    with _open(src, password) as pdf:
        _check_unsigned(pdf)
        strip_all_metadata(pdf)
        if lang:
            set_language(pdf, lang)
        _save(pdf, dst)


# --------------------------------------------------------------------------- #
# XMP yardımcıları (PDF'ten bağımsız, geçici bellek içi PDF ile)
# --------------------------------------------------------------------------- #

XMP_LIST = "Seq/Liste"
XMP_SET = "Bag/Küme"
XMP_TEXT = "metin"


def _tmp_pdf_with_xmp(xml: str) -> Pdf:
    tmp = Pdf.new()
    set_xmp(tmp, xml)
    return tmp


def xmp_to_items(xml: str) -> list[tuple[str, str, str]]:
    """XMP'yi (özellik, değer, tür) satırlarına çevirir."""
    rows: list[tuple[str, str, str]] = []
    if not xml or not xml.strip():
        return rows
    with _tmp_pdf_with_xmp(xml) as tmp:
        meta = tmp.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False)
        for key in list(meta.keys()):
            try:
                value = meta[key]
            except Exception:  # noqa: BLE001 - yapı (struct) gibi desteklenmeyen tipler
                rows.append((_short_key(key), "<karmaşık yapı – Ham XML sekmesinden düzenleyin>", "yapı"))
                continue
            if isinstance(value, list):
                rows.append((_short_key(key), " ; ".join(map(str, value)), XMP_LIST))
            elif isinstance(value, set):
                rows.append((_short_key(key), " ; ".join(sorted(map(str, value))), XMP_SET))
            else:
                rows.append((_short_key(key), str(value), XMP_TEXT))
    return rows


try:
    from pikepdf.models.metadata._constants import DEFAULT_NAMESPACES as _PIKE_NS
    _NS_TO_PREFIX = {uri: prefix for uri, prefix in _PIKE_NS}
except ImportError:  # pikepdf iç yapısı değişirse temel listeye düş
    _NS_TO_PREFIX = {
        "http://purl.org/dc/elements/1.1/": "dc",
        "http://ns.adobe.com/pdf/1.3/": "pdf",
        "http://ns.adobe.com/xap/1.0/": "xmp",
        "http://ns.adobe.com/xap/1.0/mm/": "xmpMM",
        "http://ns.adobe.com/xap/1.0/rights/": "xmpRights",
        "http://www.aiim.org/pdfa/ns/id/": "pdfaid",
    }


def _short_key(qname: str) -> str:
    """'{http://purl.org/dc/elements/1.1/}title' -> 'dc:title' (bilinmeyen ad alanı aynen kalır)."""
    if qname.startswith("{"):
        uri, _, local = qname[1:].partition("}")
        prefix = _NS_TO_PREFIX.get(uri)
        if prefix:
            return f"{prefix}:{local}"
    return qname


def items_to_xmp(base_xml: str, rows: list[tuple[str, str, str]]) -> str:
    """Tablo satırlarını temel XMP'ye uygular ve yeni XML döndürür."""
    with _tmp_pdf_with_xmp(base_xml) as tmp:
        with tmp.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
            wanted = {k for k, _, kind in rows if kind != "yapı"}
            keep_struct = {k for k, _, kind in rows if kind == "yapı"}
            for key in list(meta.keys()):
                short = _short_key(key)
                if short not in wanted and short not in keep_struct:
                    del meta[key]
            for key, value, kind in rows:
                if kind == "yapı" or not key.strip():
                    continue
                if kind == XMP_LIST:
                    meta[key] = [v.strip() for v in value.split(";") if v.strip()]
                elif kind == XMP_SET:
                    meta[key] = {v.strip() for v in value.split(";") if v.strip()}
                else:
                    meta[key] = value
        return tmp.Root.Metadata.read_bytes().decode("utf-8") if "/Metadata" in tmp.Root else ""


def info_to_xmp(base_xml: str, info: list[InfoEntry]) -> str:
    """Yalnızca Info alanlarından oluşan yeni XMP döndürür (base_xml'deki diğer veriler atılır)."""
    with Pdf.new() as tmp:
        for entry in info:
            key = _normalize_key(entry.key)
            if entry.kind != KIND_OTHER and entry.value:
                tmp.docinfo[key] = _make_value(tmp, entry.kind, entry.value)
        sync_docinfo_to_xmp(tmp)
        return tmp.Root.Metadata.read_bytes().decode("utf-8") if "/Metadata" in tmp.Root else ""
