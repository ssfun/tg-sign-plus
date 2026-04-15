from __future__ import annotations

import re


def clean_text_for_match(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    text = re.sub(r'[\u2600-\u27bf]', '', text)
    text = re.sub(r'[\u2B50]', '', text)
    text = re.sub(r'[\s\u200b\u200e\u200f\u202a-\u202e]', '', text)
    text = re.sub(r'[!"#$%&\'()*+,-./:;<=>?@\[\]^_`{|}~，。！？；：“”‘’（）【】《》]', '', text)
    return text.strip().lower()


def clean_text_for_send(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u200b\u200e\u200f\u202a-\u202e\ufeff]', '', text)
    text = re.sub(r'\s+', '', text)
    return text.strip()
