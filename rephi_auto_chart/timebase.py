from __future__ import annotations

from fractions import Fraction
from math import floor
from typing import List


def seconds_to_beat_tuple(seconds: float, bpm: float, precision: int = 192) -> List[int]:
    beats = max(0.0, seconds) * bpm / 60.0
    whole = floor(beats)
    frac = Fraction(beats - whole).limit_denominator(max(1, precision))
    if frac.numerator == frac.denominator:
        whole += 1
        frac = Fraction(0, 1)
    return [int(whole), int(frac.numerator), int(frac.denominator)]


def beat_tuple_to_beats(value: list[int]) -> float:
    whole, numerator, denominator = value
    denominator = denominator or 1
    return float(whole) + float(numerator) / float(denominator)


def compare_time(left: list[int], right: list[int]) -> int:
    a = beat_tuple_to_beats(left)
    b = beat_tuple_to_beats(right)
    return (a > b) - (a < b)

