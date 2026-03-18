"""Tests for Table.query_with_windows() — SQL window function support."""

from __future__ import annotations

import sqlalchemy as sa
import pytest

import hof.db.engine as engine_module
from hof.core.types import types
from hof.db.engine import Base
from hof.db.table import Column, Table
from hof.db.window import WindowColumn

# ---------------------------------------------------------------------------
# Test table (numeric scores make window functions easy to verify)
# ---------------------------------------------------------------------------


class Sale(Table):
    __tablename__ = "test_sales"
    amount = Column(types.Float, default=0.0)
    region = Column(types.String, default="")
    day = Column(types.Integer, default=0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def db(monkeypatch):
    """Fresh SQLite in-memory database for each test."""
    engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "_engine", engine)
    monkeypatch.setattr(engine_module, "_SessionLocal", session_factory)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(engine_module, "_SessionLocal", None)


def _seed(*records: tuple) -> None:
    """Create Sale rows from (amount, region, day) tuples."""
    for amount, region, day in records:
        Sale.create(amount=float(amount), region=region, day=day)


# ---------------------------------------------------------------------------
# Basic: no window columns → returns dicts
# ---------------------------------------------------------------------------


class TestNoWindowColumns:
    def test_returns_dicts(self):
        _seed((10, "A", 1), (20, "A", 2))
        rows = Sale.query_with_windows(order_by="day")
        assert isinstance(rows, list)
        assert all(isinstance(r, dict) for r in rows)

    def test_all_model_columns_present(self):
        _seed((10, "A", 1))
        rows = Sale.query_with_windows()
        assert "amount" in rows[0]
        assert "region" in rows[0]
        assert "day" in rows[0]
        assert "id" in rows[0]

    def test_limit_and_offset(self):
        for i in range(5):
            _seed((i * 10, "X", i))
        rows = Sale.query_with_windows(order_by="day", limit=2, offset=1)
        assert len(rows) == 2
        assert rows[0]["day"] == 1


# ---------------------------------------------------------------------------
# row_number
# ---------------------------------------------------------------------------


class TestRowNumber:
    def test_sequential_from_one(self):
        _seed((5, "A", 1), (10, "A", 2), (15, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[WindowColumn(key="rn", fn="row_number", order_by="day")],
        )
        assert [r["rn"] for r in rows] == [1, 2, 3]

    def test_row_number_with_pagination(self):
        """Row numbers must reflect the full dataset, not just the current page."""
        for i in range(6):
            _seed((i * 10, "A", i))
        page2 = Sale.query_with_windows(
            order_by="day",
            limit=3,
            offset=3,
            window_columns=[WindowColumn(key="rn", fn="row_number", order_by="day")],
        )
        assert [r["rn"] for r in page2] == [4, 5, 6]


# ---------------------------------------------------------------------------
# running_sum
# ---------------------------------------------------------------------------


class TestRunningSum:
    def test_accumulates_correctly(self):
        _seed((10, "A", 1), (20, "A", 2), (30, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="rt", fn="running_sum", over="amount", order_by="day")
            ],
        )
        assert [r["rt"] for r in rows] == [10.0, 30.0, 60.0]

    def test_running_sum_across_pages(self):
        """Running total on page 2 must continue from page 1, not restart."""
        _seed((100, "A", 1), (200, "A", 2), (300, "A", 3), (400, "A", 4))
        page2 = Sale.query_with_windows(
            order_by="day",
            limit=2,
            offset=2,
            window_columns=[
                WindowColumn(key="rt", fn="running_sum", over="amount", order_by="day")
            ],
        )
        assert page2[0]["rt"] == 600.0   # 100+200+300
        assert page2[1]["rt"] == 1000.0  # 100+200+300+400


# ---------------------------------------------------------------------------
# running_avg
# ---------------------------------------------------------------------------


class TestRunningAvg:
    def test_running_avg(self):
        _seed((10, "A", 1), (20, "A", 2), (30, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="ra", fn="running_avg", over="amount", order_by="day")
            ],
        )
        assert rows[0]["ra"] == pytest.approx(10.0)
        assert rows[1]["ra"] == pytest.approx(15.0)
        assert rows[2]["ra"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# cumulative_count
# ---------------------------------------------------------------------------


class TestCumulativeCount:
    def test_cumulative_count(self):
        _seed((1, "A", 1), (2, "A", 2), (3, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="cc", fn="cumulative_count", order_by="day")
            ],
        )
        assert [r["cc"] for r in rows] == [1, 2, 3]


# ---------------------------------------------------------------------------
# lag / lead
# ---------------------------------------------------------------------------


class TestLagLead:
    def test_lag_default_offset(self):
        _seed((10, "A", 1), (20, "A", 2), (30, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="prev", fn="lag", over="amount", order_by="day")
            ],
        )
        assert rows[0]["prev"] is None
        assert rows[1]["prev"] == pytest.approx(10.0)
        assert rows[2]["prev"] == pytest.approx(20.0)

    def test_lag_custom_offset(self):
        _seed((10, "A", 1), (20, "A", 2), (30, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="prev2", fn="lag", over="amount", order_by="day", offset=2)
            ],
        )
        assert rows[0]["prev2"] is None
        assert rows[1]["prev2"] is None
        assert rows[2]["prev2"] == pytest.approx(10.0)

    def test_lead(self):
        _seed((10, "A", 1), (20, "A", 2), (30, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="nxt", fn="lead", over="amount", order_by="day")
            ],
        )
        assert rows[0]["nxt"] == pytest.approx(20.0)
        assert rows[1]["nxt"] == pytest.approx(30.0)
        assert rows[2]["nxt"] is None


# ---------------------------------------------------------------------------
# delta
# ---------------------------------------------------------------------------


class TestDelta:
    def test_delta_first_row_is_none(self):
        _seed((10, "A", 1), (25, "A", 2), (40, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="d", fn="delta", over="amount", order_by="day")
            ],
        )
        assert rows[0]["d"] is None
        assert rows[1]["d"] == pytest.approx(15.0)
        assert rows[2]["d"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# rank
# ---------------------------------------------------------------------------


class TestRank:
    def test_rank_highest_first(self):
        _seed((30, "A", 1), (10, "A", 2), (20, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="rnk", fn="rank", over="amount", order_by="day")
            ],
        )
        by_day = {r["day"]: r["rnk"] for r in rows}
        assert by_day[1] == 1  # amount=30 → rank 1
        assert by_day[3] == 2  # amount=20 → rank 2
        assert by_day[2] == 3  # amount=10 → rank 3

    def test_rank_tied_values(self):
        _seed((50, "A", 1), (50, "A", 2), (10, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="rnk", fn="rank", over="amount", order_by="day")
            ],
        )
        ranks = {r["day"]: r["rnk"] for r in rows}
        assert ranks[1] == 1
        assert ranks[2] == 1   # tied
        assert ranks[3] == 3   # gap after tie


# ---------------------------------------------------------------------------
# pct_of_total
# ---------------------------------------------------------------------------


class TestPctOfTotal:
    def test_pct_sums_to_100(self):
        _seed((25, "A", 1), (25, "A", 2), (50, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="pct", fn="pct_of_total", over="amount", order_by="day")
            ],
        )
        total_pct = sum(r["pct"] for r in rows)
        assert total_pct == pytest.approx(100.0)
        assert rows[2]["pct"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# moving_avg
# ---------------------------------------------------------------------------


class TestMovingAvg:
    def test_moving_avg_frame(self):
        _seed((10, "A", 1), (20, "A", 2), (30, "A", 3), (40, "A", 4))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(
                    key="ma", fn="moving_avg", over="amount",
                    order_by="day", frame_size=3,
                )
            ],
        )
        assert rows[0]["ma"] == pytest.approx(10.0)            # only 1 row in frame
        assert rows[1]["ma"] == pytest.approx(15.0)            # (10+20)/2
        assert rows[2]["ma"] == pytest.approx(20.0)            # (10+20+30)/3
        assert rows[3]["ma"] == pytest.approx(30.0)            # (20+30+40)/3


# ---------------------------------------------------------------------------
# partition_by
# ---------------------------------------------------------------------------


class TestPartitionBy:
    def test_running_sum_resets_per_partition(self):
        _seed((10, "A", 1), (20, "A", 2), (5, "B", 3), (15, "B", 4))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(
                    key="rt", fn="running_sum", over="amount",
                    order_by="day", partition_by=["region"],
                )
            ],
        )
        by_day = {r["day"]: r["rt"] for r in rows}
        assert by_day[1] == pytest.approx(10.0)   # A: 10
        assert by_day[2] == pytest.approx(30.0)   # A: 10+20
        assert by_day[3] == pytest.approx(5.0)    # B: 5  (reset)
        assert by_day[4] == pytest.approx(20.0)   # B: 5+15

    def test_row_number_per_partition(self):
        _seed((1, "A", 1), (2, "A", 2), (3, "B", 3), (4, "B", 4))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(
                    key="rn", fn="row_number",
                    order_by="day", partition_by=["region"],
                )
            ],
        )
        by_day = {r["day"]: r["rn"] for r in rows}
        assert by_day[1] == 1  # A row 1
        assert by_day[2] == 2  # A row 2
        assert by_day[3] == 1  # B row 1 (reset)
        assert by_day[4] == 2  # B row 2


# ---------------------------------------------------------------------------
# Multiple window columns in one query
# ---------------------------------------------------------------------------


class TestMultipleWindowColumns:
    def test_two_window_columns(self):
        _seed((10, "A", 1), (20, "A", 2), (30, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="rn", fn="row_number", order_by="day"),
                WindowColumn(key="rt", fn="running_sum", over="amount", order_by="day"),
            ],
        )
        assert [r["rn"] for r in rows] == [1, 2, 3]
        assert [r["rt"] for r in rows] == [10.0, 30.0, 60.0]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_table(self):
        rows = Sale.query_with_windows(
            window_columns=[
                WindowColumn(key="rn", fn="row_number", order_by="day")
            ]
        )
        assert rows == []

    def test_single_row(self):
        _seed((42, "X", 1))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="rt", fn="running_sum", over="amount", order_by="day"),
                WindowColumn(key="d", fn="delta", over="amount", order_by="day"),
            ],
        )
        assert len(rows) == 1
        assert rows[0]["rt"] == pytest.approx(42.0)
        assert rows[0]["d"] is None   # no previous row

    def test_filters_applied_before_window(self):
        """Window functions should operate only on the filtered subset."""
        _seed((10, "A", 1), (20, "A", 2), (30, "B", 3))
        rows = Sale.query_with_windows(
            filters={"region": "A"},
            order_by="day",
            window_columns=[
                WindowColumn(key="rn", fn="row_number", order_by="day"),
                WindowColumn(key="rt", fn="running_sum", over="amount", order_by="day"),
            ],
        )
        assert len(rows) == 2
        assert [r["rn"] for r in rows] == [1, 2]
        assert rows[1]["rt"] == pytest.approx(30.0)   # only A rows: 10+20

    def test_ilike_filter(self):
        """ilike filter does case-insensitive substring match."""
        _seed((10, "North", 1), (20, "South", 2), (30, "Northeast", 3))
        rows = Sale.query_with_windows(
            filters={"region__ilike": "north"},
            order_by="day",
            window_columns=[
                WindowColumn(key="rn", fn="row_number", order_by="day"),
            ],
        )
        assert len(rows) == 2
        assert {r["region"] for r in rows} == {"North", "Northeast"}
        assert [r["rn"] for r in rows] == [1, 2]

    def test_unknown_fn_raises(self):
        _seed((1, "A", 1))
        with pytest.raises(ValueError, match="Unknown window function"):
            Sale.query_with_windows(
                window_columns=[
                    WindowColumn(key="x", fn="not_a_fn", order_by="day"),  # type: ignore[arg-type]
                ]
            )


# ---------------------------------------------------------------------------
# window_filters — filtering on computed window columns
# ---------------------------------------------------------------------------


class TestWindowFilters:
    def test_filter_on_running_sum_gte(self):
        """Only return rows where the running total has reached >= 30."""
        _seed((10, "A", 1), (20, "A", 2), (30, "A", 3))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="rt", fn="running_sum", over="amount", order_by="day")
            ],
            window_filters={"rt__gte": 30.0},
        )
        assert all(r["rt"] >= 30.0 for r in rows)
        assert len(rows) == 2  # rows 2 (30) and 3 (60)

    def test_filter_on_row_number(self):
        """Filter to a specific row number."""
        for i in range(5):
            _seed((i * 10, "A", i))
        rows = Sale.query_with_windows(
            order_by="day",
            window_columns=[
                WindowColumn(key="rn", fn="row_number", order_by="day")
            ],
            window_filters={"rn__lte": 3},
        )
        assert len(rows) == 3
        assert [r["rn"] for r in rows] == [1, 2, 3]

    def test_window_filter_with_base_filter(self):
        """window_filters and base filters can combine."""
        _seed((10, "A", 1), (20, "A", 2), (5, "B", 3), (15, "B", 4))
        rows = Sale.query_with_windows(
            filters={"region": "A"},
            order_by="day",
            window_columns=[
                WindowColumn(key="rt", fn="running_sum", over="amount", order_by="day")
            ],
            window_filters={"rt__gt": 10.0},
        )
        assert len(rows) == 1
        assert rows[0]["rt"] == pytest.approx(30.0)
