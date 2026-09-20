"""Спинтакс: генерация вариантов текста для рассылок (как в TeleRaptor).

Синтаксис:
    {вариант1|вариант2|вариант3}
    вложенность:   {привет|здравствуйте, {друг|приятель}}
    экранирование: \\{ \\} — литеральные скобки в тексте

Подсчёт комбинаций корректно обрабатывает вложенность:
    count_combinations("{a|b}-{1|2}")   == 4   (независимые группы: произведение)
    count_combinations("{a|{b|c}}")     == 3   (вложенная группа: сумма ветвей)

Примеры:
    generate("Привет, {User|Друг}!")   -> "Привет, User!" или "Привет, Друг!"
"""
from __future__ import annotations

import random
import re

__all__ = ["SpintaxError", "count_combinations", "generate", "has_spintax", "sample_variants"]


class SpintaxError(ValueError):
    """Некорректный спинтакс (непарные/вложенные скобки)."""


# самая внутренняя группа {...}: без скобок внутри
_INNER_RE = re.compile(r"\{([^{}]*)\}")
# плейсхолдеры заменённых групп: "\x02N", где N — индекс веса
_PH_RE = re.compile(r"\x02(\d+)")

_ESC_OPEN = "\x00"
_ESC_CLOSE = "\x01"
_PLACEHOLDER = "\x02"


def _protect(text: str) -> str:
    return text.replace("\\{", _ESC_OPEN).replace("\\}", _ESC_CLOSE)


def _restore(text: str) -> str:
    return text.replace(_ESC_OPEN, "{").replace(_ESC_CLOSE, "}")


def has_spintax(text: str) -> bool:
    return "{" in text or "}" in text


def _part_combos(part: str, weights: dict[int, int]) -> int:
    """Число комбинаций фрагмента варианта (литералы + плейсхолдеры)."""
    found = _PH_RE.findall(part)
    if not found:
        return 1
    prod = 1
    for n in found:
        prod *= weights[int(n)]
    return prod


def count_combinations(text: str) -> int:
    """Число всех возможных комбинаций, с корректной вложенностью.

    Идея: раскрываем группы от самых внутренних, заменяя каждую на
    плейсхолдер с «весом». Вес группы = сумма весов её вариантов
    (вариант-литерал = 1, вариант с подгруппой = произведение её весов).
    Итог — вес строки верхнего уровня.

    Бросает SpintaxError при непарных скобках или некорректной вложенности.
    """
    t = _protect(text)
    if t.count("{") != t.count("}"):
        raise SpintaxError(f"Непарные скобки в спинтаксе: {text!r}")

    weights: dict[int, int] = {}
    counter = 0
    while "{" in t:
        m = _INNER_RE.search(t)
        if m is None:
            raise SpintaxError(f"Некорректная вложенность скобок: {text!r}")
        body = m.group(1)
        total = sum(_part_combos(var, weights) for var in body.split("|"))
        weights[counter] = total
        t = t[: m.start()] + f"{_PLACEHOLDER}{counter}" + t[m.end():]
        counter += 1
    return _part_combos(t, weights)


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
