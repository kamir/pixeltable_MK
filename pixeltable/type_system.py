import abc
from typing import Any, Optional, Tuple, Dict, Callable, List
import enum
from datetime import datetime

import PIL.Image
import sqlalchemy as sql


class ColumnType:
    @enum.unique
    class Type(enum.Enum):
        INVALID = 0
        STRING = 1
        INT = 2
        FLOAT = 3
        BOOL = 4
        TIMESTAMP = 5
        IMAGE = 6
        DICT = 7
        ARRAY = 8

    @enum.unique
    class DType(enum.Enum):
        """
        Base type used in images and arrays
        """
        BOOL = 0,
        INT8 = 1,
        INT16 = 2,
        INT32 = 3,
        INT64 = 4,
        UINT8 = 5,
        UINT16 = 6,
        UINT32 = 7,
        UINT64 = 8,
        FLOAT16 = 9,
        FLOAT32 = 10,
        FLOAT64 = 11

    scalar_types = {Type.STRING, Type.INT, Type.FLOAT, Type.BOOL, Type.TIMESTAMP}

    def __init__(self, t: Type):
        self._type = t

    @property
    def type_enum(self) -> Type:
        return self._type

    def serialize(self) -> Dict:
        return {'type': self._type.value}

    #@classmethod
    #def deserialize(cls, d: Dict) -> 'ColumnType':
        #return None

    @classmethod
    def make_type(cls, t: Type) -> 'ColumnType':
        """
        TODO: replace with deserialize(d: Dict)
        """
        assert t != cls.Type.INVALID
        if t == cls.Type.STRING:
            return StringType()
        if t == cls.Type.INT:
            return IntType()
        if t == cls.Type.FLOAT:
            return FloatType()
        if t == cls.Type.BOOL:
            return BoolType()
        if t == cls.Type.TIMESTAMP:
            return TimestampType()
        if t == cls.Type.IMAGE:
            return ImageType()
        if t == cls.Type.DICT:
            return DictType()
        if t == cls.Type.ARRAY:
            return ArrayType()

    def __str__(self) -> str:
        return self.Type.name.lower()

    def __eq__(self, other: object) -> bool:
        assert isinstance(other, ColumnType)
        if type(self) != type(other):
            return False
        for member_var in vars(self).keys():
            if getattr(self, member_var) != getattr(other, member_var):
                return False
        return True

    def is_scalar_type(self) -> bool:
        return self._type in self.scalar_types

    def is_invalid_type(self) -> bool:
        return self._type == self.Type.INVALID

    def is_string_type(self) -> bool:
        return self._type == self.Type.STRING

    def is_int_type(self) -> bool:
        return self._type == self.Type.INT

    def is_float_type(self) -> bool:
        return self._type == self.Type.FLOAT

    def is_bool_type(self) -> bool:
        return self._type == self.Type.BOOL

    def is_timestamp_type(self) -> bool:
        return self._type == self.Type.TIMESTAMP

    def is_image_type(self) -> bool:
        return self._type == self.Type.IMAGE

    def is_dict_type(self) -> bool:
        return self._type == self.Type.DICT

    def is_array_type(self) -> bool:
        return self._type == self.Type.ARRAY

    def to_sql(self) -> str:
        """
        Return corresponding SQL type.
        """
        assert self._type != self.Type.INVALID
        if self._type == self.Type.STRING:
            return 'VARCHAR'
        if self._type == self.Type.INT:
            return 'INTEGER'
        if self._type == self.Type.FLOAT:
            return 'FLOAT'
        if self._type == self.Type.BOOL:
            return 'BOOLEAN'
        if self._type == self.Type.TIMESTAMP:
            return 'INTEGER'
        if self._type == self.Type.IMAGE:
            # the URL
            return 'VARCHAR'
        if self._type == self.Type.DICT:
            return 'VARCHAR'
        if self._type == self.Type.ARRAY:
            return 'BLOB'
        assert False

    def to_sa_type(self) -> Any:
        """
        Return corresponding SQLAlchemy type.
        return type Any: there doesn't appear to be a superclass for the sqlalchemy types
        """
        assert self._type != self.Type.INVALID
        if self._type == self.Type.STRING:
            return sql.String
        if self._type == self.Type.INT:
            return sql.Integer
        if self._type == self.Type.FLOAT:
            return sql.Float
        if self._type == self.Type.BOOL:
            return sql.Boolean
        if self._type == self.Type.TIMESTAMP:
            return sql.TIMESTAMP
        if self._type == self.Type.IMAGE:
            # the URL
            return sql.String
        if self._type == self.Type.DICT:
            return sql.String
        if self._type == self.Type.ARRAY:
            return sql.VARBINARY
        assert False

    @staticmethod
    def no_conversion(v: Any) -> Any:
        """
        Special return value of conversion_fn() that indicates that no conversion is necessary.
        Should not be called
        """
        assert False

    @abc.abstractmethod
    def conversion_fn(self, target: 'ColumnType') -> Optional[Callable[[Any], Any]]:
        """
        Return Callable that converts a column value of type self to a value of type 'target'.
        Returns None if conversion isn't possible.
        """
        return None


class InvalidType(ColumnType):
    def __init__(self):
        super().__init__(self.Type.INVALID)

class StringType(ColumnType):
    def __init__(self):
        super().__init__(self.Type.STRING)

    def conversion_fn(self, target: ColumnType) -> Optional[Callable[[Any], Any]]:
        if not target.is_timestamp_type():
            return None
        def convert(val: str) -> Optional[datetime]:
            try:
                dt = datetime.fromisoformat(val)
                return dt
            except ValueError:
                return None
        return convert


class IntType(ColumnType):
    def __init__(self):
        super().__init__(self.Type.INT)


class FloatType(ColumnType):
    def __init__(self):
        super().__init__(self.Type.FLOAT)


class BoolType(ColumnType):
    def __init__(self):
        super().__init__(self.Type.BOOL)


class TimestampType(ColumnType):
    def __init__(self):
        super().__init__(self.Type.TIMESTAMP)


class ImageType(ColumnType):
    @enum.unique
    class Mode(enum.Enum):
        L = 0,
        RGB = 1

        @classmethod
        def from_pil(cls, pil_mode: str) -> 'Mode':
            if pil_mode == 'L':
                return cls.L
            if pil_mode == 'RGB':
                return cls.RGB

        def to_pil(self) -> str:
            return self.name

        def num_channels(self) -> int:
            return len(self.name)

    def __init__(
            self, width: Optional[int] = None, height: Optional[int] = None, size: Optional[Tuple[int, int]] = None,
            mode: Optional[Mode] = None
    ):
        """
        TODO: does it make sense to specify only width or height?
        """
        super().__init__(self.Type.IMAGE)
        assert not(width is not None and size is not None)
        assert not(height is not None and size is not None)
        if size is not None:
            self.width = size[0]
            self.height = size[1]
        else:
            self.width = width
            self.height = height
        self.mode = mode

    @property
    def num_channels(self) -> Optional[int]:
        return None if self.mode is None else self.mode.num_channels()

    def serialize(self) -> Dict:
        result = super().serialize()
        result.update({'width': self.width, 'height': self.height, 'mode': self.mode.value})
        return result

    def conversion_fn(self, target: ColumnType) -> Optional[Callable[[Any], Any]]:
        if not target.is_image_type():
            return None
        assert isinstance(target, ImageType)
        if (target.width is None) != (target.height is None):
            # we can't resize only one dimension
            return None
        if (target.width == self.width or target.width is None) \
            and (target.height == self.height or target.height is None) \
            and (target.mode == self.mode or target.mode is None):
            # nothing to do
            return self.no_conversion
        def convert(img: PIL.Image.Image) -> PIL.Image.Image:
            if self.width != target.width or self.height != target.height:
                img = img.resize((target.width, target.height))
            if self.mode != target.mode:
                img = img.convert(target.mode.to_pil())
            return img
        return convert


class DictType(ColumnType):
    def __init__(self):
        super().__init__(self.Type.DICT)


class ArrayType(ColumnType):
    """
    TODO: enum Dtype, dtype in ctor
    """
    def __init__(
            self, shape: Optional[Tuple[int, ...]] = None, dtype: Optional[ColumnType.DType] = ColumnType.DType.INT32):
        super().__init__(self.Type.ARRAY)
        self.shape = shape
        self.dtype = dtype


class Function:
    def __init__(self, eval_fn: Callable, return_type: ColumnType, param_types: Optional[List[ColumnType]]):
        self.eval_fn = eval_fn
        self.return_type = return_type
        self.param_types = param_types

    def __call__(self, *args: object) -> 'pixeltable.exprs.FunctionCall':
        from pixeltable import exprs
        return exprs.FunctionCall(self, args)
