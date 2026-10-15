"""Belge okuyucu: bir PDF'in tüm metadata ve yapı bilgilerini bölümler halinde toplar (arayüzden bağımsız)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pikepdf
from pikepdf import Name

from . import core
from .signing import signatures_in

MAX_ROWS = 200  # uzun listelerde (sayfa, resim, font) gösterilecek en fazla satır


@dataclass
class Report:
    path: str
    doc: core.DocumentData  # Info, XMP, dosya bilgileri
    sections: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)

    def as_text(self) -> str:
        """Tüm bölümleri kopyalanabilir düz metin olarak döndürür."""
        out = []
        for title, rows in self.sections:
            out.append(f"=== {title} ===")
            width = max((len(k) for k, _ in rows), default=0)
            for key, value in rows:
                out.append(f"{key.ljust(width)} : {value}")
            out.append("")
        if self.doc.xmp.strip():
            out.append("=== Ham XMP ===")
            out.append(self.doc.xmp.strip())
        return "\n".join(out).rstrip() + "\n"

    def template(self, include_dates=True, include_custom=True, include_xmp=True) -> dict:
        """Belgedeki metadata'yı şablon biçimine çevirir."""
        fields, custom = {}, []
        for e in self.doc.info:
            if e.key in core.STANDARD_KEYS:
                if e.key in core.DATE_KEYS and not include_dates:
                    continue
                if e.value:
                    fields[e.key] = e.value
            elif include_custom and e.kind != core.KIND_OTHER:
                custom.append([e.key, e.value, e.kind])
        data = {"fields": fields, "custom": custom}
        if include_xmp and self.doc.xmp.strip():
            data["xmp"] = self.doc.xmp
        return data


def _s(obj) -> str:
    try:
        if isinstance(obj, pikepdf.Name):
            return str(obj)[1:]
        if isinstance(obj, pikepdf.String):
            return str(obj)
        return str(obj) if isinstance(obj, (int, float, bool)) else repr(obj)
    except Exception:  # noqa: BLE001
        return "<okunamadı>"


def _cap(rows: list, total: int, what: str) -> list:
    if total > MAX_ROWS:
        rows.append(("…", f"toplam {total} {what}; ilk {MAX_ROWS} gösteriliyor"))
    return rows


def _walk_xobjects(resources, seen, depth=0):
    if depth > 10 or resources is None:
        return
    for key in ("/Font",):
        if key in resources:
            for _, f in resources[key].items():
                yield "font", f
    if "/XObject" in resources:
        for _, x in resources.XObject.items():
            if not isinstance(x, pikepdf.Stream) or x.objgen in seen and x.objgen != (0, 0):
                continue
            seen.add(x.objgen)
            if x.get("/Subtype") == Name.Image:
                yield "image", x
            elif x.get("/Subtype") == Name.Form:
                yield from _walk_xobjects(x.get("/Resources"), seen, depth + 1)


def _form_fields(fields, prefix="", depth=0):
    for f in fields:
        if depth > 20:
            return
        name = prefix + str(f.get("/T", ""))
        if "/Kids" in f and any("/T" in k for k in f.Kids):
            yield from _form_fields(f.Kids, name + ".", depth + 1)
        else:
            ftype = _s(f.get("/FT", "")) or "?"
            value = f.get("/V")
            if ftype == "Sig":
                text = "dijital imza" + (" (dolu)" if value is not None else " (boş)")
            else:
                text = _s(value) if value is not None else ""
            yield name or "(adsız)", f"[{ftype}] {text}".strip()


def read_report(path: str, password: str = "") -> Report:
    doc = core.read_document(path, password)
    rep = Report(path=path, doc=doc)
    rep.sections.append(("Dosya Bilgileri", list(doc.file_info)))

    info_rows = []
    order = {k: i for i, k in enumerate(core.STANDARD_KEYS)}
    for e in sorted(doc.info, key=lambda e: order.get(e.key, len(order))):
        label = f"{core.LABELS[e.key]} ({e.key[1:]})" if e.key in core.LABELS else e.key
        value = e.value
        if e.key in core.DATE_KEYS:
            parsed = core.parse_pdf_date(e.value)
            if parsed:
                tz = parsed.strftime(" %z") if parsed.utcoffset() is not None else ""
                value = f"{e.value}  ({parsed.strftime('%d.%m.%Y %H:%M:%S')}{tz})"
        info_rows.append((label, value))
    rep.sections.append(("Belge Bilgileri (Info)", info_rows or [("—", "Info sözlüğü yok")]))

    try:
        xmp_rows = [(k, v) for k, v, _ in core.xmp_to_items(doc.xmp)]
    except Exception as exc:  # noqa: BLE001
        xmp_rows = [("hata", f"XMP çözümlenemedi: {exc}")]
    rep.sections.append(("XMP Metadata", xmp_rows or [("—", "XMP yok")]))

    with pikepdf.open(path, password=password) as pdf:
        # güvenlik ve imza
        sec = [("Şifreli", "Evet" if pdf.is_encrypted else "Hayır")]
        if pdf.is_encrypted:
            allow = pdf.allow
            perms = {
                "Yazdırma": allow.print_highres or allow.print_lowres,
                "Değiştirme": allow.modify_other,
                "Kopyalama / metin çıkarma": allow.extract,
                "Yorum ekleme": allow.modify_annotation,
                "Form doldurma": allow.modify_form,
                "Sayfa düzenleme (birleştirme)": allow.modify_assembly,
            }
            sec += [(f"İzin: {k}", "Var" if v else "Yok") for k, v in perms.items()]
        signed = signatures_in(pdf)
        sec.append(("Dijital imza", ", ".join(signed) if signed else "Yok"))
        if "/Perms" in pdf.Root and "/DocMDP" in pdf.Root.Perms:
            sec.append(("Sertifikalı belge (DocMDP)", "Evet — değişikliklere kısıtlı"))
        rep.sections.append(("Güvenlik ve İmza", sec))

        # belge yapısı
        root = pdf.Root
        struct = []
        for key, label in (("/Lang", "Dil"), ("/PageLayout", "Sayfa düzeni"), ("/PageMode", "Açılış modu"),
                           ("/Version", "Katalog sürümü")):
            if key in root:
                struct.append((label, _s(root[key])))
        mark = root.get("/MarkInfo")
        struct.append(("Etiketli PDF (Tagged)", "Evet" if mark is not None and mark.get("/Marked") else "Hayır"))
        if "/OutputIntents" in root:
            for oi in root.OutputIntents:
                struct.append(("Çıktı amacı (OutputIntent)", _s(oi.get("/OutputConditionIdentifier", oi.get("/S", "")))))
        if "/ViewerPreferences" in root:
            for k, v in root.ViewerPreferences.items():
                struct.append((f"Görüntüleyici: {str(k)[1:]}", _s(v)))
        for key, label in (("/OpenAction", "Açılış eylemi"), ("/Outlines", "Yer imleri"),
                           ("/Names", "Ad ağacı"), ("/StructTreeRoot", "Yapı ağacı")):
            if key in root:
                struct.append((label, "Var"))
        if "/PieceInfo" in root:
            struct.append(("PieceInfo (uygulama verisi)", ", ".join(str(k)[1:] for k in root.PieceInfo.keys())))
        rep.sections.append(("Belge Yapısı", struct))

        # sayfalar, fontlar, resimler
        pages, fonts, images = [], {}, []
        seen: set = set()
        for i, page in enumerate(pdf.pages, 1):
            box = page.mediabox
            w = float(box[2]) - float(box[0])
            h = float(box[3]) - float(box[1])
            rot = int(page.obj.get("/Rotate", 0))
            extra = []
            if rot:
                extra.append(f"döndürme {rot}°")
            if "/Annots" in page.obj and len(page.obj.Annots):
                extra.append(f"{len(page.obj.Annots)} açıklama/bağlantı")
            if "/Metadata" in page.obj:
                extra.append("sayfa XMP'si var")
            if i <= MAX_ROWS:
                pages.append((f"Sayfa {i}", f"{w * 25.4 / 72:.1f} × {h * 25.4 / 72:.1f} mm"
                              + (f" · {', '.join(extra)}" if extra else "")))
            for kind, obj in _walk_xobjects(page.obj.get("/Resources"), seen):
                if kind == "font":
                    name = _s(obj.get("/BaseFont", "")) or "(adsız)"
                    desc = obj.get("/FontDescriptor")
                    if desc is None and "/DescendantFonts" in obj:
                        desc = obj.DescendantFonts[0].get("/FontDescriptor")
                    embedded = desc is not None and any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                    subset = len(name) > 7 and name[6] == "+"
                    fonts[name] = (f"{_s(obj.get('/Subtype', ''))} · "
                                   f"{'gömülü' if embedded else 'gömülü değil'}{' (alt küme)' if subset else ''}")
                elif len(images) < MAX_ROWS:
                    filt = obj.get("/Filter")
                    filt = ", ".join(_s(f) for f in filt) if isinstance(filt, pikepdf.Array) else _s(filt or "")
                    images.append((f"Resim {len(images) + 1} (s.{i})",
                                   f"{int(obj.get('/Width', 0))} × {int(obj.get('/Height', 0))} px · "
                                   f"{_s(obj.get('/ColorSpace', '')) if not isinstance(obj.get('/ColorSpace'), pikepdf.Array) else _s(obj.ColorSpace[0])} · "
                                   f"{filt or 'sıkıştırmasız'} · {len(obj.read_raw_bytes()) / 1024:.0f} KB"))
        rep.sections.append(("Sayfalar", _cap(pages, len(pdf.pages), "sayfa")))
        rep.sections.append(("Fontlar", sorted(fonts.items()) or [("—", "Font yok")]))
        rep.sections.append(("Resimler", images or [("—", "Resim yok")]))

        att = []
        try:
            for name, spec in pdf.attachments.items():
                try:
                    size = len(spec.get_file().read_bytes())
                    att.append((name, f"{size / 1024:.1f} KB"))
                except Exception:  # noqa: BLE001
                    att.append((name, ""))
        except Exception:  # noqa: BLE001
            pass
        rep.sections.append(("Ekli Dosyalar", att or [("—", "Ek yok")]))

        form = []
        acro = root.get("/AcroForm")
        if acro is not None and "/Fields" in acro:
            form = list(_form_fields(acro.Fields))
        rep.sections.append(("Form Alanları", form[:MAX_ROWS] or [("—", "Form alanı yok")]))
    return rep
