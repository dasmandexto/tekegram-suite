"""Спинтакс: генерация вариантов текста для рассылок (как в TeleRaptor).

Синтаксис:
    {вариант1|вариант2|вариант3}
    вложенность:   {привет|здравствуйте, {друг|приятель}}
    экранирование: \{ \} — литеральные скобки в тексте

Примеры:
    generate("Привет, {User|Друг}!")   -> "Привет, User!" или "Привет, Друг!"
    count_combinations("{a|b}-{1|2|3}") -> 6
"""
from __future__ import annotations

import random
import re

__all__ = ["SpintaxError", "count_combinations", "generate", "has_spintax", "sample_variants"]


class SpintaxError(ValueError):
    """Некорректный спинтакс (непарные/вложенные скобки)."""


# самая внутренняя группа {...}: без скобок внутри
_INNER_RE = re.compile(r"\{([^{}]*)\}")

_ESC_OPEN = "\x00"
_ESC_CLOSE = "\x01"
_PLACEHOLDER = "\x02"


def _protect(text: str) -> str:
    return text.replace("\\{", _ESC_OPEN).replace("\\}", _ESC_CLOSE)


def _restore(text: str) -> str:
    return text.replace(_ESC_OPEN, "{").replace(_ESC_CLOSE, "}")


def has_spintax(text: str) -> bool:
    return "{" in text or "}" in text


def count_combinations(text: str) -> int:
    """Число всех возможных комбинаций (с учётом вложенности).

    Бросает SpintaxError при непарных скобках или некорректной вложенности.
    """
    t = _protect(text)
    if t.count("{") != t.count("}"):
        raise SpintaxError(f"Непарные скобки в спинтаксе: {text!r}")
    combos = 1
    out = t
    while "{" in out:
        m = _INNER_RE.search(out)
        if m is None:
            raise SpintaxError(f"Некорректная вложенность скобок: {text!r}")
        choices = m.group(1).split("|")
        combos *= len(choices)
        out = out[: m.start()] + _PLACEHOLDER + out[m.end():]
    return combos


def generate(text: str, rng: random.Random | None = None) -> str:
    """Случайный вариант спинтакса. rng — для воспроизводимости (тесты)."""
    rng = rng or random
    t = _protect(text)
    prev = None
    while t != prev:
        prev = t

        def repl(m: re.Match) -> str:
            return rng.choice(m.group(1).split("|"))

        t = _INNER_RE.sub(repl, t)
    return _restore(t)


def sample_variants(text: str, n: int = 5, seed: int | None = None) -> list[str]:
    """n случайных (без повторов) вариантов для предпросмотра."""
    rng = random.Random(seed) if seed is not None else random.Random()
    seen: list[str] = []
    attempts = 0
    while len(seen) < n and attempts < n * 20:
        variant = generate(text, rng)
        attempts += 1
        if variant not in seen:
            seen.append(variant)
    return seen
