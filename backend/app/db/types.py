"""
Custom SQLAlchemy types for CaseVault.

EmbeddingVector — a vector column that works with both:
  - PostgreSQL + pgvector (production)
  - SQLite with JSON text encoding (unit tests)

How it works
------------
SQLAlchemy TypeDecorator.load_dialect_impl() returns the physical column type
for a given dialect.  The TypeDecorator's own process_bind_param /
process_result_value are COMPOSED with the underlying type's bind/result
processors:

  bind:   process_bind_param(value) → underlying.bind_processor()(result)
  result: underlying.result_processor()(db_value) → process_result_value(result)

For PostgreSQL:
  - Column DDL: vector(384)
  - bind:   list[float] → pgvector string "[v1,v2,...,vn]"
  - result: pgvector string → list[float]

For SQLite (tests):
  - Column DDL: TEXT
  - bind:   list[float] → JSON string
  - result: JSON string → list[float]
"""

import json

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


class EmbeddingVector(TypeDecorator):
    """
    SQLAlchemy column type for embedding vectors.

    Usage:
        embedding: Mapped[list[float] | None] = mapped_column(
            EmbeddingVector(384), nullable=True
        )
    """

    impl = Text  # Fallback for SQLite and DDL inspection
    cache_ok = True

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector

                return dialect.type_descriptor(Vector(self.dim))
            except ImportError:
                pass
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            # Pass the list through; pgvector's bind_processor converts to
            # the "[v1,v2,...,vn]" wire format.
            return value if isinstance(value, list) else list(value)
        # SQLite: store as compact JSON
        return json.dumps([float(v) for v in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            # pgvector's result_processor has already converted the DB string
            # to a list[float]; just normalize to plain list.
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [float(v) for v in value.strip("[]").split(",")]
            return list(value)
        # SQLite: parse JSON
        if isinstance(value, str):
            return json.loads(value)
        return value
