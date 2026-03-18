"""Window function column specification for Table.query_with_windows()."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

WindowFn = Literal[
    "row_number",
    "running_sum",
    "running_avg",
    "lag",
    "lead",
    "delta",
    "rank",
    "pct_of_total",
    "moving_avg",
    "cumulative_count",
]


@dataclass
class WindowColumn:
    """Specification for a single SQL window function column.

    Args:
        key:          Output column name in the returned dicts (e.g. "running_total").
        fn:           Window function to apply.
        over:         Field name to aggregate/reference (required for all fns except
                      row_number and cumulative_count).
        order_by:     Field name to sort the window by. Defaults to "id".
        order_dir:    Sort direction — "asc" or "desc". Defaults to "asc".
        partition_by: Optional list of field names to partition the window by.
        offset:       Row offset for lag/lead. Defaults to 1.
        frame_size:   Number of rows in the moving average window. Defaults to 3.
    """

    key: str
    fn: WindowFn
    over: str | None = None
    order_by: str = "id"
    order_dir: Literal["asc", "desc"] = "asc"
    partition_by: list[str] = field(default_factory=list)
    offset: int = 1
    frame_size: int = 3
