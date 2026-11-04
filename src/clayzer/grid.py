"""The 3×3 position grid and relation vocabulary of ADR-0007."""

GRID = (
    "north_west", "north", "north_east",
    "west", "centre", "east",
    "south_west", "south", "south_east",
)  # fmt: skip

DIRECTIONAL = ("north_of", "south_of", "east_of", "west_of")
RELATIONS = (*DIRECTIONAL, "adjacent_to", "between", "inside")


def cell_at(col: float, row: float, size: int) -> str:
    """Grid cell for a pixel position on a square Chip of `size` pixels, north up."""
    c = min(2, max(0, int(col * 3 // size)))
    r = min(2, max(0, int(row * 3 // size)))
    return GRID[r * 3 + c]


def cell_distance(a: str, b: str) -> int:
    ia, ib = GRID.index(a), GRID.index(b)
    return max(abs(ia % 3 - ib % 3), abs(ia // 3 - ib // 3))


def directions(a: str, b: str) -> set[str]:
    """Directional relations that hold for something in cell `a` relative to cell `b`."""
    ia, ib = GRID.index(a), GRID.index(b)
    out = set()
    if ia // 3 < ib // 3:
        out.add("north_of")
    if ia // 3 > ib // 3:
        out.add("south_of")
    if ia % 3 > ib % 3:
        out.add("east_of")
    if ia % 3 < ib % 3:
        out.add("west_of")
    return out
