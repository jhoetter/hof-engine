"""Auto-generate Pydantic models from Table column definitions.

Used by the API routes to validate request bodies before passing data to the ORM.
"""

from __future__ import annotations

import inspect
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, Field, create_model

# Fields that users must never set directly (managed by the framework)
_SYSTEM_FIELDS = frozenset({"id", "created_at", "updated_at"})

# ``@function`` input models subclass ``BaseModel``; these names must not be used as
# field identifiers (they shadow ``BaseModel`` APIs and trigger Pydantic warnings).
_BASEMODEL_RESERVED_PARAM_FIELD_NAMES = frozenset({"schema"})


def _function_param_field_name(param_name: str) -> str:
    if param_name in _BASEMODEL_RESERVED_PARAM_FIELD_NAMES:
        return f"{param_name}_param"
    return param_name

# Map SQLAlchemy column types to Python types for Pydantic field generation
_SA_TYPE_MAP: list[tuple[type, type]] = [
    (sa.Integer, int),
    (sa.Float, float),
    (sa.Boolean, bool),
    (sa.Text, str),
    (sa.String, str),
    (sa.DateTime, str),
    (sa.Date, str),
    (sa.Uuid, str),
]


def _sa_type_to_python(sa_type: Any) -> type:
    """Convert a SQLAlchemy column type to the closest Python type."""
    for sa_cls, py_type in _SA_TYPE_MAP:
        if isinstance(sa_type, sa_cls):
            return py_type
    # JSONB / JSON / unknown → dict
    return Any  # type: ignore[return-value]


def build_create_schema(table_cls: Any) -> type[BaseModel]:
    """Build a Pydantic model for CREATE requests (POST /api/tables/<name>).

    - System fields (id, created_at, updated_at) are excluded.
    - Required columns become required fields.
    - Nullable / default columns become Optional with a default of None.
    """
    fields: dict[str, Any] = {}

    for col in table_cls.__table__.columns:
        if col.name in _SYSTEM_FIELDS:
            continue

        py_type = _sa_type_to_python(col.type)

        if col.nullable or col.default is not None or col.server_default is not None:
            fields[col.name] = (py_type | None, None)
        else:
            fields[col.name] = (py_type, ...)

    model_name = f"{table_cls.__name__}CreateSchema"
    return create_model(model_name, **fields)


def build_update_schema(table_cls: Any) -> type[BaseModel]:
    """Build a Pydantic model for UPDATE requests (PUT /api/tables/<name>/<id>).

    All fields are optional — callers only send fields they want to change.
    System fields are excluded.
    """
    fields: dict[str, Any] = {}

    for col in table_cls.__table__.columns:
        if col.name in _SYSTEM_FIELDS:
            continue

        py_type = _sa_type_to_python(col.type)
        fields[col.name] = (py_type | None, None)

    model_name = f"{table_cls.__name__}UpdateSchema"
    return create_model(model_name, **fields)


def build_function_input_schema(metadata: Any) -> type[BaseModel]:
    """Build a Pydantic model for function call requests.

    Uses the ParameterInfo list already extracted by the @function decorator.
    """
    py_type_map = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "dict": dict,
        "list": list,
        "Any": Any,
    }

    fields: dict[str, Any] = {}
    for param in metadata.parameters:
        raw = getattr(param.type_annotation, "__name__", str(param.type_annotation))
        py_type = py_type_map.get(raw, Any)

        field_name = _function_param_field_name(param.name)
        use_alias = field_name != param.name

        if param.required:
            if use_alias:
                fields[field_name] = (py_type, Field(..., alias=param.name))
            else:
                fields[field_name] = (py_type, ...)
        else:
            default_val = None
            if param.default is not inspect.Parameter.empty:
                try:
                    default_val = param.default
                except Exception:
                    default_val = None
            if use_alias:
                fields[field_name] = (
                    py_type | None,
                    Field(default=default_val, alias=param.name),
                )
            else:
                fields[field_name] = (py_type | None, default_val)

    model_name = f"{metadata.name.replace('_', ' ').title().replace(' ', '')}InputSchema"
    return create_model(model_name, **fields)
