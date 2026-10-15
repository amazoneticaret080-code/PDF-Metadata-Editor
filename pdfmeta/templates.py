"""Metadata şablonlarının JSON dosyasında saklanması (arayüzden bağımsız).

Şablon biçimi:
    {"fields": {"/Title": "...", ...}, "custom": [["/Anahtar", "değer", "metin"], ...]}
"fields" içinde boş değer: tek dosyada alanı temizler, toplu düzenlemede alanı siler.
İsteğe bağlı "xmp": ham XMP XML'i (Belge Okuyucu'dan kaydedilen şablonlarda bulunur).
"""
from __future__ import annotations

import json
import os


def default_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "PDFMetadataDuzenleyici", "sablonlar.json")


def _normalize(data: dict) -> dict:
    fields = data.get("fields") or {}
    custom = data.get("custom") or []
    out = {
        "fields": {str(k): str(v) for k, v in fields.items()},
        "custom": [[str(c) for c in row[:3]] for row in custom if len(row) >= 3],
    }
    if str(data.get("xmp") or "").strip():
        out["xmp"] = str(data["xmp"])
    return out


class TemplateStore:
    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = json.load(fh)
            return {str(name): _normalize(t) for name, t in (raw.get("templates") or {}).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            return {}

    def _write(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "templates": self._data}, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def names(self) -> list[str]:
        return sorted(self._data, key=str.casefold)

    def get(self, name: str) -> dict | None:
        t = self._data.get(name)
        return _normalize(t) if t is not None else None

    def put(self, name: str, data: dict) -> None:
        self._data[name] = _normalize(data)
        self._write()

    def delete(self, name: str) -> None:
        if self._data.pop(name, None) is not None:
            self._write()
