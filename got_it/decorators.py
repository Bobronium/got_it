import functools
import inspect
import logging
from collections import defaultdict, OrderedDict
from types import FunctionType
from typing import Any, Type, Union, Set, Dict, Optional, Tuple, no_type_check, cast

import pydantic

from .args import ArgsSpec
from .parsing import parse_args, parse_result
from .typing import (
    T,
    Wrapped,
    Decorator,
    DictStrAny,
    TupleAny,
    STRICT_TYPES_MAPPING,
    ModelType,
    FieldDefinitions,
    TypeAny
)

__all__ = ('all_methods', 'got_it', 'ignore_it')

logger = logging.getLogger(__name__)

IGNORE_IF_FIRST = ('mcs', 'cls', 'self')

empty = object()


def ignore_it(obj: T) -> T:
    """
    Special marker when using `got_it` for a class
    indicates that function should not be decorated

    Can be replaced with @got_it(exclude={'method_name'})
    """
    obj.__is_ignored__ = True  # type: ignore
    return obj


class GotItMeta(type):
    @no_type_check
    def __call__(
            cls,
            maybe_obj_to_wrap: Wrapped = None,  # use @got_it without call, if no parameters needed
            **kwargs,
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
        :param validators: validators for pydantic.create_model

        :return: parametrized decorator or decorated function/class
        """
        init_cls = super().__call__
        if maybe_obj_to_wrap is None:
            return init_cls(**kwargs)

        to_wrap = maybe_obj_to_wrap
        # check, that is not a config given as positional arg, just in case.
        # we can't just check that is function cause it can be a class to decorate
        is_config = isinstance(to_wrap, type) and issubclass(to_wrap, pydantic.BaseConfig) or any(
            not attr.startswith('_') and attr in pydantic.BaseConfig.__dict__ for attr in to_wrap.__dict__
        )
        if is_config:
            # seems like config was passed as a positional arg
            # throwing it to class to get TypeError
            init_cls(to_wrap, **kwargs)

        # instancing class and wrapping object straight away
        return init_cls(**kwargs).wrap(to_wrap)


class got_it(metaclass=GotItMeta):
    def __init__(
            self,
            *,
            config: Type[pydantic.BaseConfig] = None,
            strict_types: bool = False,
            ignore_untyped: bool = False,
            wrap_returns: bool = None,
            **validators: classmethod
    ) -> None:
        self.config = config
        self.strict_types = strict_types
        self.ignore_untyped = ignore_untyped
        self.check_returns = wrap_returns
        self.validators = validators

    def wrap(self, wrapped: Wrapped) -> Wrapped:
        if inspect.isclass(wrapped):
            raise TypeError('wrapping class is not supported, use `all_methods(got_it)` instead')

        is_method = False
        wrapped_type: TypeAny = type(wrapped)
        if wrapped_type in (staticmethod, classmethod):
            is_method = True
            wrapped = wrapped.__func__  # type: ignore

        wrapped = cast(FunctionType, wrapped)
        args_spec = self.get_args_spec(wrapped)
        args_model = self.prepare_args_model(wrapped, args_spec.field_definitions)
        returns_model = self.prepare_returns_model(wrapped) if self.check_returns else None

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

    __call__ = wrap

    def get_args_spec(self, wrapped: FunctionType) -> ArgsSpec:
        sign = inspect.signature(wrapped)
        field_definitions: FieldDefinitions = OrderedDict()
        args_name = None
        kwargs_name = None
        positional_args_end = None
        for i, param in enumerate(sign.parameters.values()):
            name, annotation, default, kind, empty_ = (
                param.name, param.annotation, param.default, param.kind, param.empty
            )
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
                    annotation = Dict[str, annotation]  # type: ignore
                default = {}

            if annotation is empty_:
                no_default = (default in (empty_, None))
                arg_ignored = i == 0 and name in IGNORE_IF_FIRST
                if no_default and (self.ignore_untyped or arg_ignored):
                    annotation = Any
                elif no_default:
                    raise TypeError(f"No annotation or default value specified for argument '{name}' of {wrapped}"
                                    f"use `ignore_untyped=True` to threat such params as typing.Any")
            elif self.strict_types:
                if STRICT_TYPES_MAPPING is NotImplemented:
                    raise RuntimeError('To use strict validators install pydantic>=1.0')
                strict_type = STRICT_TYPES_MAPPING.get(annotation)
                if strict_type is not None:
                    annotation = strict_type

            if default is empty_:
                default = ...  # special value for pydantic

            field_definitions[name] = default if annotation is empty_ else (annotation, default)

        return ArgsSpec(
            field_definitions=field_definitions,
            var_args_name=args_name,
            var_kwargs_name=kwargs_name,
            args_names=tuple(field_definitions),
            positional_args_end=positional_args_end,
        )

    def prepare_args_model(self, wrapped: FunctionType, field_definitions: FieldDefinitions) -> ModelType:
        args_model = pydantic.create_model(
            model_name=getattr(wrapped, '__qualname__', 'callable') + '_args_model',
            __config__=self.config,
            __validators__=self.validators,
            **field_definitions
        )

        args_model.__config__.extra = pydantic.Extra.forbid
        logging.debug(f'Created arguments model for {wrapped} with fields: {args_model.__fields__}')
        wrapped.__args_model__ = args_model  # type: ignore
        return args_model

    def prepare_returns_model(self, wrapped: FunctionType) -> ModelType:
        return_type = wrapped.__annotations__['return']
        returns_model = pydantic.create_model(
            model_name=getattr(wrapped, '__qualname__', 'callable') + '_returns_model',
            __config__=self.config,
            returns=(return_type, ...)
        )
        logging.debug(f'Created returns model for {wrapped} with fields: {returns_model.__fields__}')
        wrapped.__returns_model__ = returns_model  # type: ignore

        return returns_model


def all_methods(wrapper: got_it, include_bases: bool = False, exclude: Set[str] = None, include: Set[str] = None):
    """
    Wraps all methods of class, except magic and private methods

    @all_methods(got_it)
    class MyClass:
        ...

    :param wrapper: parametrized instance of got_it, or just plain got_it class
    :param include_bases: include methods from bases when decorating a class
    :param exclude: exclude methods when decorating a class
    :param include: force include methods, which are excluded by default (e. g. magic and private methods)
    """
    exclude = exclude or set()
    include = include or set()
    # we need to keep track of seen methods separately for each class,
    # so parametrized `all_methods` could be reused as many times as needed
    seen_methods: Dict[TypeAny, Set[str]] = defaultdict(exclude.copy)

    def wrap(wrapped_cls: TypeAny) -> TypeAny:
        seen = seen_methods[wrapped_cls]
        classes_to_wrap = wrapped_cls.__mro__ if include_bases else (wrapped_cls,)
        for cls in classes_to_wrap:  # type: ignore
            for attr, obj in cls.__dict__.items():
                if attr in seen:
                    continue

                seen.add(attr)  # so we won't override wrapped_cls methods with bases methods
                is_ignored = getattr(obj, '__is_ignored__', False)
                is_sundered = attr.startswith('_')  # or dundered, whatever
                if is_ignored or (inspect.isclass(obj) or is_sundered and attr not in include):  # type: ignore
                    continue

                obj_type = type(obj)
                if obj_type is property:
                    new_fset = wrapper(obj.fset)
                    new_obj = obj.setter(new_fset)
                    setattr(wrapped_cls, attr, new_obj)
                elif callable(obj) or obj_type in (classmethod, staticmethod):
                    new_obj = wrapper(obj)
                    setattr(wrapped_cls, attr, new_obj)
        return wrapped_cls

    return wrap
