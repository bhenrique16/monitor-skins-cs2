"""Leitura e comparação de nomes de itens (market hash name)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

WEARS = {
    "Factory New": "FN",
    "Minimal Wear": "MW",
    "Field-Tested": "FT",
    "Well-Worn": "WW",
    "Battle-Scarred": "BS",
}
WEAR_NAMES = {code: name for name, code in WEARS.items()}
WEAR_PT = {
    "FN": "Nova de Fábrica",
    "MW": "Pouco Usada",
    "FT": "Testada em Campo",
    "WW": "Bem Desgastada",
    "BS": "Veterana de Guerra",
}
# Limite superior (exclusivo) do float de cada desgaste.
_FLOAT_RANGES = (("FN", 0.07), ("MW", 0.15), ("FT", 0.38), ("WW", 0.45), ("BS", 1.01))
_WEAR_RE = re.compile(r"\s*\((" + "|".join(re.escape(w) for w in WEARS) + r")\)\s*$")
_STATTRAK_RE = re.compile(r"StatTrak\s*™?\s*")


@dataclass(frozen=True)
class ParsedName:
    base: str  # nome sem desgaste, StatTrak e Souvenir
    wear: str | None  # FN, MW, FT, WW, BS ou None
    stattrak: bool
    souvenir: bool


def parse(name: str) -> ParsedName:
    text = " ".join(str(name).split())
    wear = None
    match = _WEAR_RE.search(text)
    if match:
        wear = WEARS[match.group(1)]
        text = text[: match.start()]
    stattrak = "StatTrak" in text
    if stattrak:
        text = _STATTRAK_RE.sub("", text)
    souvenir = text.startswith("Souvenir ")
    if souvenir:
        text = text[len("Souvenir "):]
    return ParsedName(" ".join(text.split()), wear, stattrak, souvenir)


def key(name: str) -> str:
    """Chave de comparação: mesma skin, qualquer desgaste, com ou sem StatTrak."""
    base = parse(name).base.replace("★", " ").replace("|", " ")
    base = unicodedata.normalize("NFKC", base).casefold()
    return " ".join(base.split())


def same_skin(a: str, b: str) -> bool:
    return key(a) == key(b)


def search_text(name: str) -> str:
    """Texto para os campos de busca das lojas: sem símbolos nem desgaste."""
    base = parse(name).base.replace("★", " ").replace("|", " ").replace("™", " ")
    return " ".join(base.split())


def plain_base(name: str) -> str:
    """Nome base sem a estrela, mantendo a barra: "Skeleton Knife | Slaughter"."""
    return " ".join(parse(name).base.replace("★", " ").split())


def slug_text(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def slugify(name: str) -> str:
    """Slug da skin, sem desgaste nem StatTrak: "skeleton-knife-slaughter"."""
    return slug_text(parse(name).base)


def short(name: str) -> str:
    """Nome completo com o desgaste abreviado, para o assunto do e-mail."""
    text = " ".join(str(name).split())
    match = _WEAR_RE.search(text)
    if match:
        text = text[: match.start()] + " (" + WEARS[match.group(1)] + ")"
    return text


def wear_from_float(value: float) -> str:
    for code, upper in _FLOAT_RANGES:
        if value < upper:
            return code
    return "BS"


def wear_label(code: str | None) -> str:
    if not code:
        return "sem desgaste"
    return f"{WEAR_PT[code]} ({code})"
