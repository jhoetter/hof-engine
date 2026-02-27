"""Tests for hof.core.types."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from hof.core.types import types


class TestBasicTypes:
    def test_string_type(self):
        assert isinstance(types.String, sa.String)

    def test_text_type(self):
        assert isinstance(types.Text, sa.Text)

    def test_integer_type(self):
        assert isinstance(types.Integer, sa.Integer)

    def test_float_type(self):
        assert isinstance(types.Float, sa.Float)

    def test_boolean_type(self):
        assert isinstance(types.Boolean, sa.Boolean)

    def test_datetime_type(self):
        assert isinstance(types.DateTime, sa.DateTime)

    def test_date_type(self):
        assert isinstance(types.Date, sa.Date)

    def test_uuid_type(self):
        assert isinstance(types.UUID, sa.Uuid)


class TestJsonType:
    def test_json_is_jsonb(self):
        assert isinstance(types.JSON, postgresql.JSONB)


class TestFileType:
    def test_file_is_string(self):
        assert isinstance(types.File, sa.String)


class TestEnumType:
    def test_enum_returns_string(self):
        result = types.Enum("a", "b", "c")
        assert isinstance(result, sa.String)

    def test_enum_with_single_value(self):
        result = types.Enum("only")
        assert isinstance(result, sa.String)

    def test_enum_with_many_values(self):
        result = types.Enum("new", "active", "archived", "deleted")
        assert isinstance(result, sa.String)


class TestStringWithLength:
    def test_string_default_length(self):
        result = types.String_(255)
        assert isinstance(result, sa.String)

    def test_string_custom_length(self):
        result = types.String_(100)
        assert isinstance(result, sa.String)
        assert result.length == 100

    def test_string_large_length(self):
        result = types.String_(1024)
        assert result.length == 1024


class TestDatetimeTimezone:
    def test_datetime_is_timezone_aware(self):
        assert types.DateTime.timezone is True
