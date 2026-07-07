"""Database layer: DuckDB connection + repository. All SQL is isolated here."""

from analyzer.db.repository import Repository, connect

__all__ = ["Repository", "connect"]
