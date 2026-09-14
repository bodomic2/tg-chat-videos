"""Нормализация строк: общий ключ для группировки и сравнения названий."""

import re
import unicodedata

QUOTES = str.maketrans({
    "«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‟": '"',
    "‘": "'", "’": "'", "‚": "'", "`": "'", "´": "'",
})


def norm_key(value):
    """Ключ группировки: регистр, кавычки, ё/е, лишние пробелы и хвостовая пунктуация."""
    value = unicodedata.normalize("NFKC", value or "").translate(QUOTES)
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"\s+", " ", value).strip()
    value = value.strip("\"'.,!?;:-–—… ")
    value = re.sub(r"^the\s+", "", value)
    return re.sub(r"\s+", " ", value).strip()
