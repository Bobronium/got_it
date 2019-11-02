from typing import Tuple, OrderedDict, Optional, Union, Any, Type, NamedTuple

from .typing import TupleAny, DictStrAny, RestoredArgs


class ArgsSpec(NamedTuple):
    field_definitions: OrderedDict[str, Union[Any, Tuple[Type[Any], Any]]]
    args_names: Tuple[str, ...]
    var_args_name: Optional[str]
    var_kwargs_name: Optional[str]
    positional_args_end: int


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

    known_kwargs, additional_kwargs = {}, {}
    for name, arg in all_kwargs.items():
        if name in known_args_names:
            known_kwargs[name] = arg
        else:
            additional_kwargs[name] = arg

    return known_args, additional_args, known_kwargs, additional_kwargs
