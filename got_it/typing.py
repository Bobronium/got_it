from typing import Tuple, Any, Iterable, Dict, TypeVar, Union, Callable, Type
import warnings

import pydantic

try:
    from pydantic import StrictInt, StrictFloat, StrictStr, StrictBool
except ImportError:
    warnings.warn('Strict validators not found. To be able to use strict type check please install pydantic>=1.0')
    STRICT_TYPES_MAPPING = NotImplemented
else:
    STRICT_TYPES_MAPPING = {int: StrictInt, float: StrictFloat, bool: StrictBool, str: StrictStr}

try:
    from typing import Protocol
except ImportError:
    try:
        from typing_extensions import Protocol
    except ImportError:
        Protocol = NotImplemented

TupleAny = Tuple[Any, ...]
IterableAny = Iterable[Any]
DictStrAny = Dict[str, Any]
RestoredArgs = Tuple[TupleAny, TupleAny, DictStrAny, DictStrAny]
ParsedArgs = Tuple[Iterable[Any], TupleAny, DictStrAny, DictStrAny]
ModelType = Type[pydantic.BaseModel]

T = TypeVar('T')

if Protocol is NotImplemented:
    Wrapped = Union[Callable[..., T], Type[Any]]
    Decorator = Callable[[Wrapped, bool], Wrapped]

else:
    class Wrapped(Protocol):
        __args_model__: Type[pydantic.BaseModel]

        def __call__(self, *args, **kwargs) -> T: ...


    class Decorator(Protocol):
        def __call__(self, wrapped: Wrapped, decorating_method: bool = False) -> Wrapped: ...
