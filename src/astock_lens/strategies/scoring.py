"""Cross-sectional ranking helpers.

One definition of "percentile" serves both the per-factor blend and the final
score. Two implementations would eventually disagree, and a ranking whose
meaning drifts between its layers is worse than no ranking at all.
"""

from collections.abc import Mapping


def percentile_ranks(values: Mapping[str, float]) -> dict[str, float]:
    """Rank each key within the population, returning a value in `(0, 1]`.

    The smallest value maps to `1/n` and the largest to `1.0`, so a
    single-element population maps to `1.0` — it is both first and last. Ties
    share the average of the ranks they occupy, which is what keeps two symbols
    with identical factor values from being ordered arbitrarily.

    An empty population returns an empty mapping rather than raising: "there
    was nothing to rank" is a normal answer, not a failure.
    """
    count = len(values)
    if count == 0:
        return {}

    ordered = sorted(values.items(), key=lambda item: item[1])
    ranks: dict[str, float] = {}

    start = 0
    while start < count:
        end = start
        while end + 1 < count and ordered[end + 1][1] == ordered[start][1]:
            end += 1
        # Positions are 1-based, so the run start..end occupies `start + 1`
        # through `end + 1`; every member takes their average.
        average_position = ((start + 1) + (end + 1)) / 2
        for position in range(start, end + 1):
            ranks[ordered[position][0]] = average_position / count
        start = end + 1

    return ranks
