import functools
import inspect
import logging
from collections import defaultdict
from typing import Any, Type, Union, Set, Dict, Optional, OrderedDict, Tuple

import pydantic

from .args import ArgsSpec
from .parsing import parse_args, parse_result
from .typing import Wrapped, Decorator, T, DictStrAny, TupleAny, STRICT_TYPES_MAPPING, ModelType

__all__ = ('got_it', 'got_it_everywhere', 'ignore_it')

logger = logging.getLogger(__name__)

IGNORE_IF_FIRST = ('mcs', 'cls', 'self')

empty = object()


def ignore_it(obj: T) -> T:
    """
    Special marker when using `got_it` for a class
    indicates that function should not be decorated

    Can be replaced with @got_it(exclude={'method_name'})
    """
    obj.__is_ignored__ = True
    return obj


class GotItMeta(type):
    def __call__(
            cls,
            *one_callable_to_wrap: Wrapped,  # use @got_it without call, if no parameters needed
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
        :param include_bases: include methods from bases when decorating a class
        :param exclude: exclude methods when decorating a class
        :param include: force include methods, which are excluded by default (e. g. magic methods)
        :param validators: validators for pydantic.create_model

        :return: parametrized decorator or decorated function/class
        """
        # init class
        decorator = super().__call__(**kwargs)
        if not one_callable_to_wrap:
            return decorator

        to_wrap = one_callable_to_wrap[0]
        # check, that is not a config given as positional arg, just in case.
        # we can't just check that is function cause it can be a class to decorate
        is_config = isinstance(to_wrap, type) and issubclass(to_wrap, pydantic.BaseConfig) or any(
            not attr.startswith('_') and attr in pydantic.BaseConfig.__dict__ for attr in to_wrap.__dict__
        )
        if is_config or len(one_callable_to_wrap) > 1:
            raise TypeError(f'`got_it` supports keywords arguments only')
        return decorator.wrap(to_wrap)


class got_it(metaclass=GotItMeta):
    def __init__(
            self,
            *,
            config: Type[pydantic.BaseConfig] = None,
            strict_types: bool = False,
            ignore_untyped: bool = False,
            check_returns: bool = None,
            **validators: classmethod
    ) -> None:
        self.config = config
        self.strict_types = strict_types
        self.ignore_untyped = ignore_untyped
        self.check_returns = check_returns
        self.validators = validators

    def wrap(self, wrapped):
        if inspect.isclass(wrapped):
            raise TypeError('wrapping class is not supported, use `got_it_everywhere` instead')

        is_method = False
        wrapped_type = type(wrapped)
        if wrapped_type in (staticmethod, classmethod):
            is_method = True
            wrapped = wrapped.__func__

        args_spec = self.get_args_spec(wrapped)
        args_model, returns_model = self.prepare_models(wrapped, args_spec)

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

    def get_args_spec(self, wrapped: Wrapped) -> ArgsSpec:
        sign = inspect.signature(wrapped)
        field_definitions = OrderedDict()
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
                    annotation = Dict[str, annotation]
                default = {}

            if annotation is empty_:
                no_default = (default in (empty_, None))
                arg_ignored = i == 0 and name in IGNORE_IF_FIRST
                if no_default and (self.ignore_untyped or arg_ignored):
                    annotation = Any
                elif no_default:
                    raise TypeError(f"No annotation or default value specified for argument '{name}' of {wrapped}"
                                    f"use `ignore_untyped=False` to threat such params as typing.Any")
            elif self.strict_types:
                if STRICT_TYPES_MAPPING is NotImplemented:
                    raise RuntimeError('To use strict validators install pydantic>=1.0')
                strict_type = STRICT_TYPES_MAPPING.get(annotation)
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

    def prepare_models(self, wrapped: Wrapped, args_spec: ArgsSpec) -> Tuple[ModelType, Optional[ModelType]]:
        args_model = pydantic.create_model(
            model_name=getattr(wrapped, '__qualname__', 'callable') + '_args_model',
            __config__=self.config,
            __validators__=self.validators,
            **args_spec.field_definitions
        )

        args_model.__config__.extra = pydantic.Extra.forbid
        logging.debug(f'Created arguments model for {wrapped} with fields: {args_model.__fields__}')
        wrapped.__args_model__ = args_model

        if self.check_returns:
            class ReturnModel(pydantic.BaseModel):
                Config = self.config
                __annotations__ = {'__root__': wrapped.__annotations__['return']}

            logging.debug(f'Created returns model for {wrapped} with fields: {ReturnModel.__fields__}')
            wrapped.__returns_model__ = ReturnModel
            return args_model, ReturnModel

        wrapped.__returns_model__ = None
        return args_model, None


class got_it_everywhere(got_it):
    """Wraps methods of a class"""
    def __init__(
            self,
            *,
            config: Type[pydantic.BaseConfig] = None,
            strict_types: bool = False,
            ignore_untyped: bool = False,
            check_returns: bool = None,
            include_bases: bool = False,
            exclude: Set[str] = None,
            include: Set[str] = None,
            **validators: classmethod
    ) -> None:
        super().__init__(
            config=config,
            strict_types=strict_types,
            ignore_untyped=ignore_untyped,
            check_returns=check_returns,
            **validators
        )
        self.include_bases = include_bases
        self.exclude = exclude or set()
        self.include = include or set()
        # we need to keep track of seen methods separately for each class,
        # so once got_it inited, it could be reused as many times as needed
        self.seen_methods: Dict[Type[Any], Set[str]] = defaultdict(self.exclude.copy)

    def wrap(self, wrapped_cls: Type[Any]):
        seen = self.seen_methods[wrapped_cls]
        for cls in wrapped_cls.__mro__ if self.include_bases else (wrapped_cls,):
            for attr, obj in cls.__dict__.items():
                if attr in seen:
                    continue

                seen.add(attr)  # so we won't override wrapped_cls methods with bases methods
                is_ignored = getattr(obj, '__is_ignored__', False)
                is_dundered = attr.startswith('__') and attr.endswith('__')
                if is_ignored or (inspect.isclass(obj) or is_dundered and attr not in self.include):
                    continue

                obj_type = type(obj)
                if obj_type is property:
                    new_fset = super().wrap(obj.fset)
                    new_obj = obj.setter(new_fset)
                    setattr(wrapped_cls, attr, new_obj)
                elif callable(obj) or obj_type in (classmethod, staticmethod):
                    new_obj = super().wrap(obj)
                    setattr(wrapped_cls, attr, new_obj)
        return wrapped_cls

    __call__ = wrap
