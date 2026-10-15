"""PDF boyut küçültme motoru (arayüzden bağımsız).

1. Kayıpsız: kullanılmayan kaynaklar silinir, akışlar yeniden sıkıştırılır, nesne akışları kullanılır.
2. Hedefe ulaşılamazsa resimler giderek düşen kalite / çözünürlükle JPEG olarak yeniden kodlanır;
   hedefe sığan en yüksek kalite seçilir (ikili arama). Metadata (Info + XMP) aynen korunur.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass

import pikepdf
from pikepdf import Name, Pdf, PdfImage

from .signing import signatures_in

# (ölçek, JPEG kalitesi, açıklama) — yüksek kaliteden düşüğe
LEVELS = [
    (1.00, 92, "resimler çok yüksek kalite"),
    (1.00, 85, "resimler yüksek kalite"),
    (1.00, 75, "resimler iyi kalite"),
    (0.85, 70, "resimler %85 çözünürlük"),
    (0.70, 65, "resimler %70 çözünürlük"),
    (0.60, 60, "resimler %60 çözünürlük"),
    (0.50, 55, "resimler %50 çözünürlük"),
    (0.40, 50, "resimler %40 çözünürlük"),
    (0.33, 45, "resimler %33 çözünürlük"),
    (0.25, 40, "resimler %25 çözünürlük"),
    (0.20, 35, "resimler %20 çözünürlük (düşük kalite)"),
]
MIN_IMAGE_BYTES = 8 * 1024  # bundan küçük resimlere dokunulmaz
MIN_SIDE = 16  # piksel


@dataclass
class Result:
    size: int  # bayt
    level: str  # uygulanan yöntem
    reached: bool  # hedefe ulaşıldı mı
    images: int  # yeniden kodlanan resim sayısı


class Cancelled(Exception):
    pass


def human(n: int) -> str:
    return f"{n / 1024 / 1024:.2f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


def _images(pdf: Pdf):
    """Belgedeki resim XObject'lerini (formların içindekiler dahil) birer kez döndürür."""
    seen = set()
    smasks = set()

    def walk(resources, depth=0):
        if depth > 10 or resources is None or "/XObject" not in resources:
            return
        for _, xobj in resources.XObject.items():
            if not isinstance(xobj, pikepdf.Stream):
                continue
            key = xobj.objgen
            if key in seen and key != (0, 0):
                continue
            seen.add(key)
            sub = xobj.get("/Subtype")
            if sub == Name.Image:
                if "/SMask" in xobj:
                    smasks.add(xobj.SMask.objgen)
                yield xobj
            elif sub == Name.Form:
                yield from walk(xobj.get("/Resources"), depth + 1)

    found = []
    for page in pdf.pages:
        found.extend(walk(page.obj.get("/Resources")))
    return [x for x in found if x.objgen not in smasks]


def _recompress_image(xobj: pikepdf.Stream, scale: float, quality: int) -> bool:
    if xobj.get("/ImageMask") or "/Decode" in xobj:
        return False
    if int(xobj.get("/BitsPerComponent", 8)) < 8:
        return False  # 1 bit (taranmış siyah-beyaz) resimler JPEG'e uygun değil
    raw_len = len(xobj.read_raw_bytes())
    if raw_len < MIN_IMAGE_BYTES:
        return False
    try:
        img = PdfImage(xobj).as_pil_image()
    except Exception:  # noqa: BLE001 - desteklenmeyen kodlama/renk uzayı
        return False
    from PIL import Image

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if scale < 1.0:
        w, h = max(MIN_SIDE, int(img.width * scale)), max(MIN_SIDE, int(img.height * scale))
        if w < img.width:
            img = img.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    data = buf.getvalue()
    if len(data) >= raw_len:
        return False
    xobj.write(data, filter=Name.DCTDecode)
    xobj.Width = img.width
    xobj.Height = img.height
    xobj.ColorSpace = Name.DeviceGray if img.mode == "L" else Name.DeviceRGB
    xobj.BitsPerComponent = 8
    for key in ("/DecodeParms", "/Intent"):
        if key in xobj:
            del xobj[key]
    return True


def _build(src: str, password: str, level: tuple | None) -> tuple[bytes, int]:
    """Bir seviyeyi bellekte uygular -> (pdf baytları, yeniden kodlanan resim sayısı)."""
    with pikepdf.open(src, password=password) as pdf:
        if signatures_in(pdf):
            raise ValueError("Belge dijital olarak imzalanmış; küçültmek imzayı bozacağı için yapılamaz.")
        try:
            pdf.remove_unreferenced_resources()
        except Exception:  # noqa: BLE001
            pass
        count = 0
        if level is not None:
            scale, quality, _ = level
            for xobj in _images(pdf):
                if _recompress_image(xobj, scale, quality):
                    count += 1
        buf = io.BytesIO()
        pdf.save(
            buf,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            stream_decode_level=pikepdf.StreamDecodeLevel.generalized,
            fix_metadata_version=False,
            encryption=bool(pdf.is_encrypted),
        )
        return buf.getvalue(), count


def compress(src: str, dst: str, target: int, password: str = "", progress=None) -> Result:
    """src'yi target bayta (veya altına) indirmeye çalışır ve dst'ye yazar.

    Hedefe ulaşılamazsa elde edilebilen en küçük hali yazılır (Result.reached=False).
    progress(metin, yüzde) her adımda çağrılır; Cancelled fırlatarak iptal edebilir.
    """
    if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
        raise ValueError("Kaynak dosyanın üzerine yazılamaz.")
    report = progress or (lambda *_: None)
    original = os.path.getsize(src)

    report("Kayıpsız sıkıştırma deneniyor…", 5)
    data, _ = _build(src, password, None)
    best = (data, "kayıpsız sıkıştırma (kalite değişmedi)", 0)
    if len(data) > original:  # kayıpsız deneme büyüttüyse orijinali koru
        with open(src, "rb") as fh:
            best = (fh.read(), "değişiklik yok (dosya zaten sıkıştırılmış)", 0)

    if len(best[0]) > target:
        # hedefe sığan en yüksek kaliteli seviye: ikili arama
        lo, hi = 0, len(LEVELS) - 1
        fit = None
        smallest = best
        tried = 0
        steps = max(1, len(LEVELS).bit_length() + 1)
        while lo <= hi:
            mid = (lo + hi) // 2
            tried += 1
            report(f"Deneniyor: {LEVELS[mid][2]}…", 10 + int(85 * tried / steps))
            data, n = _build(src, password, LEVELS[mid])
            candidate = (data, LEVELS[mid][2], n)
            if len(data) < len(smallest[0]):
                smallest = candidate
            if len(data) <= target:
                fit = candidate
                hi = mid - 1  # daha yüksek kaliteyi dene
            else:
                lo = mid + 1
        best = fit or smallest

    data, label, images = best
    with open(dst, "wb") as fh:
        fh.write(data)
    report("Bitti.", 100)
    return Result(size=len(data), level=label, reached=len(data) <= target, images=images)
