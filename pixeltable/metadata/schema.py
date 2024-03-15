from typing import Optional, List, Dict, get_type_hints, Type, Any, TypeVar, Tuple, Union
import platform
import uuid
import dataclasses

import sqlalchemy as sql
from sqlalchemy import Integer, String, Boolean, BigInteger, LargeBinary
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import ForeignKey, UniqueConstraint, ForeignKeyConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()

T = TypeVar('T')

def md_from_dict(data_class_type: Type[T], data: Any) -> T:
    """Re-instantiate a dataclass instance that contains nested dataclasses from a dict."""
    if dataclasses.is_dataclass(data_class_type):
        fieldtypes = {f: t for f, t in get_type_hints(data_class_type).items()}
        return data_class_type(**{f: md_from_dict(fieldtypes[f], data[f]) for f in data})
    elif hasattr(data_class_type, '__origin__'):
        if data_class_type.__origin__ is Union and type(None) in data_class_type.__args__:
            # Handling Optional types
            non_none_args = [arg for arg in data_class_type.__args__ if arg is not type(None)]
            if len(non_none_args) == 1:
                return md_from_dict(non_none_args[0], data) if data is not None else None
        elif data_class_type.__origin__ is list:
            return [md_from_dict(data_class_type.__args__[0], elem) for elem in data]
        elif data_class_type.__origin__ is dict:
            key_type = data_class_type.__args__[0]
            val_type = data_class_type.__args__[1]
            return {key_type(key): md_from_dict(val_type, val) for key, val in data.items()}
        elif data_class_type.__origin__ is tuple:
            return tuple(md_from_dict(arg_type, elem) for arg_type, elem in zip(data_class_type.__args__, data))
    else:
        return data


# structure of the stored metadata:
# - each schema entity that grows somehow proportionally to the data (# of output_rows, total insert operations,
#   number of schema changes) gets its own table
# - each table has an 'md' column that basically contains the payload
# - exceptions to that are foreign keys without which lookups would be too slow (ex.: TableSchemaVersions.tbl_id)
# - the md column contains a dataclass serialized to json; this has the advantage of making changes to the metadata
#   schema easier (the goal is not to have to rely on some schema migration framework; if that breaks for some user,
#   it would be very difficult to patch up)

@dataclasses.dataclass
class SystemInfoMd:
    schema_version: int


class SystemInfo(Base):
    """A single-row table that contains system-wide metadata."""
    __tablename__ = 'systeminfo'
    dummy = sql.Column(Integer, primary_key=True, default=0, nullable=False)
    md = sql.Column(JSONB, nullable=False)  # SystemInfoMd


@dataclasses.dataclass
class DirMd:
    name: str


class Dir(Base):
    __tablename__ = 'dirs'

    id = sql.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    parent_id = sql.Column(UUID(as_uuid=True), ForeignKey('dirs.id'), nullable=True)
    md = sql.Column(JSONB, nullable=False)


@dataclasses.dataclass
class ColumnHistory:
    """
    Records when a column was added/dropped, which is needed to GC unreachable storage columns
    (a column that was added after table snapshot n and dropped before table snapshot n+1 can be removed
    from the stored table).
    One record per column (across all schema versions).
     """
    col_id: int
    schema_version_add: int
    schema_version_drop: Optional[int]


@dataclasses.dataclass
class ViewMd:
    is_snapshot: bool

    # (table id, version); for mutable views, all versions are None
    base_versions: List[Tuple[str, Optional[int]]]

    # filter predicate applied to the base table; view-only
    predicate: Optional[Dict[str, Any]]

    # ComponentIterator subclass; only for component views
    iterator_class_fqn: Optional[str]

    # args to pass to the iterator class constructor; only for component views
    iterator_args: Optional[Dict[str, Any]]


@dataclasses.dataclass
class TableMd:
    name: str

    # monotonically increasing w/in Table for both data and schema changes, starting at 0
    current_version: int
    # each version has a corresponding schema version (current_version >= current_schema_version)
    current_schema_version: int

    # used to assign Column.id
    next_col_id: int

    # - used to assign the rowid column in the storage table
    # - every row is assigned a unique and immutable rowid on insertion
    next_row_id: int

    column_history: Dict[int, ColumnHistory]  # col_id -> ColumnHistory

    view_md: Optional[ViewMd]


class Table(Base):
    """
    Table represents both tables and views.

    Views are in essence a subclass of tables, because they also store materialized columns. The differences are:
    - views have a base, which is either a (live) table or a snapshot
    - views can have a filter predicate
    """
    __tablename__ = 'tables'

    MAX_VERSION = 9223372036854775807  # 2^63 - 1

    id = sql.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    dir_id = sql.Column(UUID(as_uuid=True), ForeignKey('dirs.id'), nullable=False)
    md = sql.Column(JSONB, nullable=False)  # TableMd


@dataclasses.dataclass
class TableVersionMd:
    created_at: float  # time.time()
    version: int
    schema_version: int


class TableVersion(Base):
    __tablename__ = 'tableversions'
    tbl_id = sql.Column(UUID(as_uuid=True), ForeignKey('tables.id'), primary_key=True, nullable=False)
    version = sql.Column(BigInteger, primary_key=True, nullable=False)
    md = sql.Column(JSONB, nullable=False)  # TableVersionMd


@dataclasses.dataclass
class SchemaColumn:
    """
    Records the logical (user-visible) schema of a table.
    Contains the full set of columns for each new schema version: one record per (column x schema version).
    """
    pos: int
    name: str
    col_type: dict
    is_pk: bool
    value_expr: Optional[dict]
    stored: Optional[bool]
    # if True, creates vector index for this column
    is_indexed: bool


@dataclasses.dataclass
class TableSchemaVersionMd:
    schema_version: int
    preceding_schema_version: Optional[int]
    columns: Dict[int, SchemaColumn]  # col_id -> SchemaColumn
    num_retained_versions: int
    comment: str


# versioning: each table schema change results in a new record
class TableSchemaVersion(Base):
    __tablename__ = 'tableschemaversions'

    tbl_id = sql.Column(UUID(as_uuid=True), ForeignKey('tables.id'), primary_key=True, nullable=False)
    schema_version = sql.Column(BigInteger, primary_key=True, nullable=False)
    md = sql.Column(JSONB, nullable=False)  # TableSchemaVersionMd


@dataclasses.dataclass
class FunctionMd:
    name: str
    md: dict  # Function.md


class Function(Base):
    """
    User-defined functions that are not library functions (ie, aren't available at runtime as a symbol in a known
    module).
    Functions without a name are anonymous functions used in the definition of a computed column.
    Functions that have names are also assigned to a database and directory.
    We store the Python version under which a Function was created (and the callable pickled) in order to warn
    against version mismatches.
    """
    __tablename__ = 'functions'

    id = sql.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    dir_id = sql.Column(UUID(as_uuid=True), ForeignKey('dirs.id'), nullable=True)
    md = sql.Column(JSONB, nullable=False)  # FunctionMd
    eval_obj = sql.Column(LargeBinary, nullable=True)  # Function.eval_fn
    init_obj = sql.Column(LargeBinary, nullable=True)  # Function.init_fn
    update_obj = sql.Column(LargeBinary, nullable=True)  # Function.update_fn
    value_obj = sql.Column(LargeBinary, nullable=True)  # Function.value_fn
    python_version = sql.Column(
        String, nullable=False, default=platform.python_version, onupdate=platform.python_version)
