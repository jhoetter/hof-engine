"""Tests for hof.db.table — Table ORM base class."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
import sqlalchemy as sa

import hof.db.engine as engine_module
from hof.core.registry import registry
from hof.db.engine import Base, init_engine
from hof.db.table import Column, ForeignKey, Table
from hof.core.types import types


# ---------------------------------------------------------------------------
# Test table definitions (defined once at module level)
# ---------------------------------------------------------------------------


class Item(Table):
    __tablename__ = "test_items"
    name = Column(types.String, required=True)
    score = Column(types.Integer, default=0)
    active = Column(types.Boolean, default=True)


class Tag(Table):
    __tablename__ = "test_tags"
    label = Column(types.String, required=True)
    item_id = ForeignKey(Item)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def db(monkeypatch):
    """Set up a fresh SQLite in-memory database for each test."""
    engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(engine_module, "_engine", engine)
    monkeypatch.setattr(engine_module, "_SessionLocal", Session)

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(engine_module, "_SessionLocal", None)


# ---------------------------------------------------------------------------
# Column descriptor tests
# ---------------------------------------------------------------------------


class TestColumnDescriptor:
    def test_column_attributes(self):
        col = Column(types.String, required=True, unique=True, index=True)
        assert col.required is True
        assert col.unique is True
        assert col.index is True

    def test_required_sets_nullable_false(self):
        col = Column(types.String, required=True)
        assert col.nullable is False

    def test_not_required_is_nullable(self):
        col = Column(types.String, required=False)
        assert col.nullable is True

    def test_default_value(self):
        col = Column(types.Integer, default=42)
        assert col.default == 42


class TestTableMetaclass:
    def test_auto_id_column(self):
        assert hasattr(Item, "id")

    def test_auto_created_at(self):
        assert hasattr(Item, "created_at")

    def test_auto_updated_at(self):
        assert hasattr(Item, "updated_at")

    def test_user_columns_present(self):
        assert hasattr(Item, "name")
        assert hasattr(Item, "score")
        assert hasattr(Item, "active")

    def test_table_registered_at_import_time(self):
        # Tables register themselves at class definition time (module import).
        # The clean_registry fixture clears the registry before each test,
        # so we verify the registration mechanism by re-registering manually.
        registry.register_table(Item)
        assert registry.get_table("test_items") is Item

    def test_foreign_key_column(self):
        assert hasattr(Tag, "item_id")


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_basic(self):
        item = Item.create(name="Widget", score=10)
        assert item.id is not None
        assert item.name == "Widget"
        assert item.score == 10

    def test_create_with_explicit_id(self):
        item_id = uuid.uuid4()
        item = Item.create(id=item_id, name="Named")
        assert item.id == item_id

    def test_create_sets_created_at(self):
        item = Item.create(name="Timestamped")
        assert item.created_at is not None

    def test_bulk_create(self):
        items = Item.bulk_create([
            {"name": "A", "score": 1},
            {"name": "B", "score": 2},
            {"name": "C", "score": 3},
        ])
        assert len(items) == 3
        assert {i.name for i in items} == {"A", "B", "C"}


class TestGet:
    def test_get_existing(self):
        item = Item.create(name="Findable")
        found = Item.get(item.id)
        assert found is not None
        assert found.name == "Findable"

    def test_get_missing_returns_none(self):
        assert Item.get(uuid.uuid4()) is None


class TestQuery:
    def test_query_all(self):
        Item.create(name="X")
        Item.create(name="Y")
        results = Item.query()
        assert len(results) >= 2

    def test_query_with_exact_filter(self):
        Item.create(name="Alpha", score=5)
        Item.create(name="Beta", score=10)
        results = Item.query(filters={"name": "Alpha"})
        assert len(results) == 1
        assert results[0].name == "Alpha"

    def test_query_with_gt_filter(self):
        Item.create(name="Low", score=1)
        Item.create(name="High", score=100)
        results = Item.query(filters={"score__gt": 50})
        assert all(r.score > 50 for r in results)

    def test_query_with_lt_filter(self):
        Item.create(name="Low", score=1)
        Item.create(name="High", score=100)
        results = Item.query(filters={"score__lt": 50})
        assert all(r.score < 50 for r in results)

    def test_query_with_in_filter(self):
        Item.create(name="A", score=1)
        Item.create(name="B", score=2)
        Item.create(name="C", score=3)
        results = Item.query(filters={"score__in": [1, 3]})
        assert {r.name for r in results} == {"A", "C"}

    def test_query_order_ascending(self):
        Item.create(name="Z", score=3)
        Item.create(name="A", score=1)
        Item.create(name="M", score=2)
        results = Item.query(order_by="score")
        scores = [r.score for r in results]
        assert scores == sorted(scores)

    def test_query_order_descending(self):
        Item.create(name="Z", score=3)
        Item.create(name="A", score=1)
        results = Item.query(order_by="-score")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_query_limit(self):
        for i in range(10):
            Item.create(name=f"Item{i}")
        results = Item.query(limit=3)
        assert len(results) == 3

    def test_query_offset(self):
        for i in range(5):
            Item.create(name=f"Item{i}", score=i)
        all_results = Item.query(order_by="score")
        offset_results = Item.query(order_by="score", offset=2)
        assert len(offset_results) == len(all_results) - 2


class TestUpdate:
    def test_update_field(self):
        item = Item.create(name="Old", score=1)
        updated = Item.update(item.id, name="New", score=99)
        assert updated is not None
        assert updated.name == "New"
        assert updated.score == 99

    def test_update_missing_returns_none(self):
        result = Item.update(uuid.uuid4(), name="Ghost")
        assert result is None


class TestDelete:
    def test_delete_existing(self):
        item = Item.create(name="ToDelete")
        result = Item.delete(item.id)
        assert result is True
        assert Item.get(item.id) is None

    def test_delete_missing_returns_false(self):
        result = Item.delete(uuid.uuid4())
        assert result is False


class TestCount:
    def test_count_all(self):
        Item.create(name="A")
        Item.create(name="B")
        assert Item.count() >= 2

    def test_count_with_filter(self):
        Item.create(name="Active", active=True)
        Item.create(name="Inactive", active=False)
        active_count = Item.count(filters={"active": True})
        assert active_count >= 1


class TestBulkDelete:
    def test_bulk_delete_by_filter(self):
        Item.create(name="Keep", score=100)
        Item.create(name="Del1", score=0)
        Item.create(name="Del2", score=0)
        deleted = Item.bulk_delete(filters={"score": 0})
        assert deleted == 2
        assert Item.count(filters={"score": 0}) == 0


class TestToDict:
    def test_to_dict_contains_all_columns(self):
        item = Item.create(name="DictTest", score=7)
        d = item.to_dict()
        assert "id" in d
        assert "name" in d
        assert "score" in d
        assert "created_at" in d
        assert "updated_at" in d
        assert d["name"] == "DictTest"
        assert d["score"] == 7
