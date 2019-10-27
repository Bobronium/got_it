import functools
import inspect
import logging

from typing import Any, Type, Union, Set

import pydantic

from got_it.args import get_args_spec
from .parsing import prepare_models, parse_args, parse_result
from .typing import Wrapped, Decorator, T

__all__ = ('got_it', 'ignore_it')

logger = logging.getLogger(__name__)


def got_it(
        *one_callable_to_wrap: Wrapped,  # use @got_it without call, if no parameters needed
        config: Type[pydantic.BaseConfig] = None,
        strict_types: bool = False,
        ignore_untyped: bool = False,
        check_returns: bool = None,
        include_bases: bool = False,
        exclude: Set[str] = None,
        include: Set[str] = None,
        **validators: classmethod
) -> Union[Wrapped, Decorator]:
    """
    Decorator for runtime validation of arguments of a function

    Example:
        @got_it
        def func(a: int, b: float, *ints: int, **kwargs: bool):
            print(a, b, ints, kwargs)

        func('1', '6', 1, '2', 3, f='f', t='true', zero=0, one=1)
        # prints:
        # (1, 6.0, (1, 2, 3), {'f': False, 't': True, 'z': False, 'o': True})

    :param one_callable_to_wrap: reserved for callable when decorating func without params like this: @got_it
    :param config: config for pydantic model
    :param strict_types: enable strict validation for str, int, bool and float (pydantic>=1.0)
    :param ignore_untyped: threat arguments without type annotation and default like Any
    :param check_returns: tells whether to check return annotation or not
    :param include_bases: include methods from bases when decorating a class
    :param exclude: exclude methods when decorating a class
    :param include: force include methods, which are excluded by default (e. g. magic methods)
    :param validators: validators for pydantic.create_model

    :return: parametrized decorator or decorated function/class
    """
    to_wrap = None
    if one_callable_to_wrap:
        to_wrap = one_callable_to_wrap[0]
        # check, that is not a config given as positional arg, just in case.
        # we can't just check that is function cause it can be a class to decorate
        is_config = isinstance(to_wrap, type) and issubclass(to_wrap, pydantic.BaseConfig) or any(
            not attr.startswith('_') and attr in pydantic.BaseConfig.__dict__ for attr in to_wrap.__dict__
        )
        if is_config:
            raise TypeError(f'`got_it` supports keywords arguments only')

    def decorator(wrapped: Wrapped, decorating_class=False) -> Wrapped:
        if inspect.isclass(wrapped):
            return _wrap_class_methods(wrapped, decorator, exclude or set(), include or set(), include_bases)
        elif (exclude or include_bases) and not decorating_class:
            raise TypeError('`exclude` and `include_bases` args can be used only when decorate a class')

        is_method = False
        wrapped_type = type(wrapped)
        if wrapped_type in (staticmethod, classmethod):
            is_method = True
            wrapped = wrapped.__func__

        args_spec = get_args_spec(wrapped, ignore_untyped, strict_types)
        args_model, returns_model = prepare_models(
            wrapped=wrapped,
            args_spec=args_spec,
            config=config,
            validators=validators,
            check_returns=check_returns
        )

        if inspect.iscoroutine(wrapped):
            async def wrapper(*args, **kwargs):
                known_args, args, known_kwargs, kwargs, = parse_args(args_model, wrapped, args_spec, args, kwargs)
                result = await wrapped(*known_args, *args, **known_kwargs, **kwargs)
                if returns_model:
                    return parse_result(returns_model, result)
                return result
        else:
            def wrapper(*args, **kwargs):
                known_args, args, known_kwargs, kwargs, = parse_args(args_model, wrapped, args_spec, args, kwargs)
                result = wrapped(*known_args, *args, **known_kwargs, **kwargs)
                if returns_model:
                    return parse_result(returns_model, result)
                return result

        new_obj = functools.wraps(wrapped)(wrapper)
        if is_method:
            return wrapped_type(new_obj)
        return new_obj

    if to_wrap:
        return decorator(to_wrap)
    return decorator


def ignore_it(obj: T) -> T:
    """
    Special marker when using `got_it` for a class
    indicates that function should not be decorated

    Can be replaced with @got_it(exclude={'method_name'})
    """
    obj.__is_ignored__ = True
    return obj


def _wrap_class_methods(
        wrapped_cls: Type[Any], decorator: Decorator, exclude: Set[str], include: Set[str], include_bases: bool
):
    exclude.update({'__class__', '__init_subclass__', '__subclasshook__', '__new__'})
    for cls in wrapped_cls.__mro__ if include_bases else (wrapped_cls,):
        for attr, obj in cls.__dict__.items():
            if attr in exclude:
                continue

            exclude.add(attr)  # so we won't override wrapped_cls methods with bases methods
            is_ignored = getattr(obj, '__is_ignored__', False)
            is_dundered = attr.startswith('__') and attr.endswith('__')

            if is_ignored or is_dundered and attr not in include:
                continue

            obj_type = type(obj)
            if obj_type is property:
                new_fset = decorator(obj.fset, decorating_class=True)
                new_obj = obj.setter(new_fset)
                setattr(wrapped_cls, attr, new_obj)
            elif callable(obj) or obj_type in (classmethod, staticmethod):
                new_obj = decorator(obj, decorating_class=True)
                setattr(wrapped_cls, attr, new_obj)

    return wrapped_cls
