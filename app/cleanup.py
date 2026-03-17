# -*- coding: utf-8 -*-
"""
cleanup.py - WR Voice
Curatare text transcris pe 4 nivele, local si offline.
"""

import re

_FILLERS_RO = [
    r"\b(ă+|î+|ș+)\b",
    r"\b(ăm|eem|eee|mmm|cumva)\b",
    r"\b(gen|adică|deci|practic|oarecum)\b",
    r"\b(știi|știu eu|hai|nah|ehe)\b",
    r"\b(păi și|pai si|ei bine|dă)\b",
    r"\b(cum să zic|cum ar fi|de fapt)\b",
]

_FILLERS_EN = [
    r"\b(um+|uh+|hmm+|err+|ah+)\b",
    r"\b(like|you know|I mean|basically|literally)\b",
    r"\b(so+|well+|right|okay so|and so)\b",
    r"\b(kind of|sort of|I guess|you see)\b",
]

ALL_FILLERS = [re.compile(p, re.IGNORECASE) for p in _FILLERS_RO + _FILLERS_EN]

_EXTRA_FILLERS_L4 = [re.compile(p, re.IGNORECASE) for p in [
    r"\b(în principiu|în general|ca să zic așa|ca să zic asa|cum ar veni)\b",
    r"\b(mai mult sau mai puțin|mai mult sau mai putin|undeva la|cam pe acolo)\b",
    r"\b(să zicem|sa zicem|hai să zicem|hai sa zicem|să spunem|sa spunem)\b",
    r"\b(nu știu|nu stiu|habar n-am|habar nam|mă întreb|ma intreb)\b",
    r"\b(evident|evident că|bineînțeles|bineinteles|desigur|firește|fireste)\b",
    r"\b(practic|practic vorbind|în esență|in esenta|pe scurt)\b",
    r"\b(deci|deci practic|deci gen)\b",
    r"\b(to be honest|honestly speaking|truth be told|if you will)\b",
    r"\b(at the end of the day|when all is said and done)\b",
    r"\b(needless to say|it goes without saying|obviously)\b",
    r"\b(more or less|kind of sort of|somewhere around)\b",
]]

# Pre-compile frequently used patterns
_RE_COMMA_CONJ = re.compile(
    r",\s*(și|că|dar|sau|ori|iar|deci|însă|ca|cu|pe|în|la|de|să)\b",
    re.IGNORECASE,
)
_RE_COMMA = re.compile(r",")
_RE_COMMA_DOT = re.compile(r",\.")
_RE_COMMA_END = re.compile(r",\s*$")
_RE_COMMA_START = re.compile(r"^,\s*")
_RE_SPACE_COMMA = re.compile(r"\s+,")
_RE_MULTI_SPACE = re.compile(r"\s+")
_RE_WORD_REPEAT = re.compile(r"\b(\w+)(\s+\1){1,4}\b", re.IGNORECASE)
_RE_STUTTER = re.compile(r"\b\w{1,2}-\s+")
_RE_SPACE_PUNCT = re.compile(r"\s+([.,!?])")
_RE_LEADING_CONJ_RO = re.compile(r"^(și|dar|că|deci|pentru că|însă)\s+", re.IGNORECASE)
_RE_LEADING_CONJ_EN = re.compile(r"^(and|but|so|because|however)\s+", re.IGNORECASE)
_RE_LEADING_REPEAT = re.compile(r"^(\w+\s+){0,2}(\w+\s+)\2", re.IGNORECASE)
_RE_SENTENCE_CAP = re.compile(r"([.!?])\s+([a-zăîșț])")
_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_RE_DOT_LOWER = re.compile(r"\.\s+([a-zăîșț])")


def _fix_punctuation(text: str) -> str:
    if not text:
        return text

    t = _RE_COMMA_CONJ.sub(r" \1", text)
    words = t.split()
    if t.count(",") > max(0, len(words) // 8):
        t = _RE_COMMA.sub("", t)
    t = _RE_COMMA_DOT.sub(".", t)
    t = _RE_COMMA_END.sub("", t.strip())
    t = _RE_COMMA_START.sub("", t)
    t = _RE_SPACE_COMMA.sub(",", t)
    t = _RE_MULTI_SPACE.sub(" ", t).strip()
    return t


def level1_raw(text: str) -> str:
    return text.strip()


def level2_balanced(text: str) -> str:
    if not text:
        return text

    t = text.strip()
    for pattern in ALL_FILLERS:
        t = pattern.sub(" ", t)

    t = _RE_WORD_REPEAT.sub(r"\1", t)
    t = _RE_STUTTER.sub("", t)
    t = _RE_MULTI_SPACE.sub(" ", t).strip()
    t = _RE_SPACE_PUNCT.sub(r"\1", t)

    if t:
        t = t[0].upper() + t[1:]

    t = _fix_punctuation(t)
    return t if t else text.strip()


def level3_aggressive(text: str) -> str:
    if not text:
        return text

    t = level2_balanced(text)
    t = _RE_LEADING_REPEAT.sub(r"\2", t)
    t = _RE_LEADING_CONJ_RO.sub("", t)
    t = _RE_LEADING_CONJ_EN.sub("", t)
    t = _RE_MULTI_SPACE.sub(" ", t).strip()

    if t and t[-1] not in ".!?":
        t += "."

    t = _RE_SENTENCE_CAP.sub(
        lambda m: m.group(1) + " " + m.group(2).upper(),
        t,
    )

    if t:
        t = t[0].upper() + t[1:]

    t = _fix_punctuation(t)
    return t if t else text.strip()


def level4_mega_aggressive(text: str) -> str:
    if not text:
        return text

    t = level3_aggressive(text)

    for pattern in _EXTRA_FILLERS_L4:
        t = pattern.sub(" ", t)

    sentences = [s.strip() for s in _RE_SENTENCE_SPLIT.split(t) if s.strip()]
    if len(sentences) >= 3:
        filtered = [sentences[0]]
        for sentence in sentences[1:]:
            if len(sentence.split()) >= 3:
                filtered.append(sentence)
        sentences = filtered
    t = " ".join(sentences)

    t = _RE_DOT_LOWER.sub(lambda m: " " + m.group(1), t)
    t = _RE_MULTI_SPACE.sub(" ", t).strip()

    if t and t[-1] not in ".!?":
        t += "."

    if t:
        t = t[0].upper() + t[1:]

    t = _fix_punctuation(t)
    return t if t else text.strip()


def clean(text: str, level: int, language: str = "ro") -> str:
    if level == 1:
        return level1_raw(text)
    if level == 2:
        return level2_balanced(text)
    if level == 3:
        return level3_aggressive(text)
    return level4_mega_aggressive(text)


LEVEL_LABELS = {
    1: "1 - Raw",
    2: "2 - Balansat",
    3: "3 - Agresiv",
    4: "4 - Mega Agresiv",
}
