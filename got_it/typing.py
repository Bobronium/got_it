import warnings
from typing import Tuple, Any, Iterable, Dict, Union, Callable, Type, OrderedDict, TypeVar

import pydantic

try:
    from pydantic import StrictInt, StrictFloat, StrictStr, StrictBool
except ImportError:
    warnings.warn('Strict validators not found. To be able to use strict type check please install pydantic>=1.0')
    STRICT_TYPES_MAPPING = NotImplemented
else:
    STRICT_TYPES_MAPPING = {int: StrictInt, float: StrictFloat, bool: StrictBool, str: StrictStr}

T = TypeVar('T')

TypeAny = Type[Any]
TupleAny = Tuple[Any, ...]
IterableAny = Iterable[Any]
DictStrAny = Dict[str, Any]
RestoredArgs = Tuple[TupleAny, TupleAny, DictStrAny, DictStrAny]
ParsedArgs = Tuple[Iterable[Any], TupleAny, DictStrAny, DictStrAny]
ModelType = Type[pydantic.BaseModel]
FieldDefinitions = OrderedDict[str, Union[Any, Tuple[Any, Any]]]
Wrapped = Union[Callable[..., Any], staticmethod, classmethod]
Decorator = Callable[[Wrapped], Wrapped]

