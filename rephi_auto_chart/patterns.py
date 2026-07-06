from __future__ import annotations


PATTERN_LIBRARY: dict[str, list[float]] = {
    "Tap Stream": [-270.0, 270.0, -405.0, 405.0],
    "Alternating": [-405.0, 405.0, -270.0, 270.0],
    "Double": [-270.0, 270.0],
    "Triple": [-270.0, 0.0, 270.0],
    "Stair": [-540.0, -270.0, 0.0, 270.0, 540.0],
    "Burst": [-540.0, -270.0, 270.0, 540.0, 0.0, 405.0],
    "Drag Chain": [-405.0, -270.0, -135.0, 0.0, 135.0, 270.0, 405.0],
    "Jack": [0.0, 0.0, 0.0, 0.0],
    "Trill": [-270.0, 270.0, -270.0, 270.0],
    "Wave": [-540.0, -270.0, 0.0, 270.0, 540.0, 270.0, 0.0, -270.0],
    "Jump": [-405.0, 405.0, -405.0, 405.0],
    "Center Expand": [0.0, -135.0, 135.0, -270.0, 270.0, -405.0, 405.0],
    "Center Close": [-405.0, 405.0, -270.0, 270.0, -135.0, 135.0, 0.0],
    "Drop Pattern": [-540.0, -270.0, 0.0, 270.0, 540.0, 270.0, 0.0, -270.0],
    "Build Pattern": [-270.0, 0.0, 270.0, -405.0, 405.0, -540.0, 540.0],
    "Outro Pattern": [-405.0, 405.0, -270.0, 270.0, 0.0],
}


DRAG_CHAIN_PATTERNS = {
    "Left->Right": [-540.0, -405.0, -270.0, -135.0, 0.0, 135.0, 270.0, 405.0, 540.0],
    "Right->Left": [540.0, 405.0, 270.0, 135.0, 0.0, -135.0, -270.0, -405.0, -540.0],
    "Stair": [-540.0, -270.0, 0.0, 270.0, 540.0],
    "Zigzag": [-405.0, 405.0, -270.0, 270.0, -135.0, 135.0],
    "Center": [-135.0, 0.0, 135.0, 0.0],
    "Wave": [-540.0, -270.0, 0.0, 270.0, 540.0, 270.0, 0.0, -270.0],
}


def pattern_names() -> list[str]:
    return sorted(PATTERN_LIBRARY)


def lane_for(pattern_name: str, index: int) -> float:
    pattern = PATTERN_LIBRARY.get(pattern_name, PATTERN_LIBRARY["Tap Stream"])
    return pattern[index % len(pattern)]


def drag_lane(pattern_name: str, index: int) -> float:
    pattern = DRAG_CHAIN_PATTERNS.get(pattern_name, DRAG_CHAIN_PATTERNS["Left->Right"])
    return pattern[index % len(pattern)]
