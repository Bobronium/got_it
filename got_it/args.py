import inspect
from typing import Tuple, Dict, Any, NamedTuple, Type, Union, OrderedDict, Optional

from .typing import TupleAny, DictStrAny, RestoredArgs, Wrapped, STRICT_TYPES_MAPPING

IGNORE_IF_FIRST = ('mcs', 'cls', 'self')

empty = object()


class ArgsSpec(NamedTuple):
    field_definitions: OrderedDict[str, Union[Any, Tuple[Type[Any], Any]]]
    args_names: Tuple[str, ...]
    var_args_name: Optional[str]
    var_kwargs_name: Optional[str]
    positional_args_end: int


def get_args_spec(
        wrapped: Wrapped, ignore_untyped: bool, strict: bool
) -> ArgsSpec:
    sign = inspect.signature(wrapped)
    field_definitions = OrderedDict()
    args_name = None
    kwargs_name = None
    positional_args_end = None
    for i, param in enumerate(sign.parameters.values()):
        name, annotation, default, kind, empty_ = param.name, param.annotation, param.default, param.kind, param.empty

        if kind == param.KEYWORD_ONLY:
            if positional_args_end is None:
                positional_args_end = i
        elif kind == param.VAR_POSITIONAL:
            if positional_args_end is None:
                positional_args_end = i
            args_name = name
            if annotation is empty_:
                annotation = TupleAny
            elif not getattr(annotation, '__origin__', None) is tuple:
                annotation = Tuple[annotation, ...]
            default = ()
        elif kind == param.VAR_KEYWORD:
            if positional_args_end is None:
                positional_args_end = i
            kwargs_name = name
            if annotation is empty_:
                annotation = DictStrAny
            else:
                annotation = Dict[str, annotation]
            default = {}

        if annotation is empty_:
            no_default = (default in (empty_, None))
            arg_ignored = i == 0 and name in IGNORE_IF_FIRST
            if no_default and (ignore_untyped or arg_ignored):
                annotation = Any
            elif no_default:
                raise TypeError(f"No annotation or default value specified for argument '{name}' of {wrapped}"
                                f"use `ignore_untyped=False` to threat such params as typing.Any")
        elif strict:
            if STRICT_TYPES_MAPPING is NotImplemented:
                raise RuntimeError('To use strict validators install pydantic>=1.0')
            strict_type = STRICT_TYPES_MAPPING.get(annotation, None)
            if strict_type is not None:
                annotation = strict_type

        if default is empty_:
            default = ...  # special value for pydantic

        field_definitions[name] = default if annotation is empty_ else (annotation, default)

    if not field_definitions:
        raise TypeError("Functions without arguments or with **kwargs only are not supported")

    return ArgsSpec(
        field_definitions=field_definitions,
        var_args_name=args_name,
        var_kwargs_name=kwargs_name,
        args_names=tuple(field_definitions),
        positional_args_end=positional_args_end,
    )


def restore_args(
        all_args: TupleAny,
        all_kwargs: DictStrAny,
        known_args_names: Tuple[str],
        known_positional_args_end: int
) -> RestoredArgs:
    """
    Maps arguments to function signature

              known_args   additional_args   known_kwargs   additional_kwargs
    def func( a, b,        *args,            c=1, d=2,      **kwargs): ...
    """
    if known_positional_args_end is None:
        known_args = all_args
        additional_args = ()
    else:
        known_args = all_args[:known_positional_args_end]
        additional_args = all_args[known_positional_args_end:]

    known_kwargs = {
        name: arg for name, arg in all_kwargs.items() if name in known_args_names
    }
    additional_kwargs = {
        name: arg for name, arg in all_kwargs.items() if name not in known_args_names
    }

    return known_args, additional_args, known_kwargs, additional_kwargs
