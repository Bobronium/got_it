import inspect
import logging
from functools import partial
from typing import Type, Tuple, Dict, Optional

import pydantic

from .args import restore_args, ArgsSpec
from .typing import Wrapped, ParsedArgs, TupleAny, DictStrAny, ModelType

# in pydantic 1.0 validate_model doesn't have attr raise_exc and always returns exception
if 'raise_exc' in inspect.getfullargspec(pydantic.validate_model).args:
    validate_model = partial(pydantic.validate_model, raise_exc=False)
else:
    validate_model = pydantic.validate_model


def parse_args(
        model: Type[pydantic.BaseModel],
        wrapped: Wrapped,
        arg_spec: ArgsSpec,
        all_args: TupleAny,
        all_kwargs: DictStrAny
) -> ParsedArgs:
    """
    Parses incoming arguments, maps it to args model and restores it back in right order
    """
    args_names = arg_spec.args_names
    var_kwargs_name = arg_spec.var_kwargs_name
    var_args_name = arg_spec.var_args_name
    positional_args_end = arg_spec.positional_args_end

    known_args, additional_args, known_kwargs, additional_kwargs = restore_args(
        all_args=all_args,
        all_kwargs=all_kwargs,
        known_args_names=args_names,
        known_positional_args_end=positional_args_end,
    )

    if additional_args:
        known_kwargs[var_args_name or 'args'] = additional_args
    if additional_kwargs:
        if var_kwargs_name:
            known_kwargs[var_kwargs_name] = additional_kwargs
        else:
            # putting values in the root of the model to get more obvious errors
            known_kwargs.update(additional_kwargs)

    # as pydantic.BaseModel doesn't support
    # positional arguments, we need to convert it
    # to kwargs before validation and restore back later
    for arg, name in zip(known_args, args_names):
        if name in all_kwargs:  # need to manually check that, otherwise kwargs will be overwritten silently
            f_name = getattr(wrapped, '__qualname__', wrapped)
            raise TypeError(f"'{f_name}' got multiple values for argument '{name}'")
        known_kwargs[name] = arg

    parsed_kwargs, _fields, validation_error = validate_model(model, known_kwargs)
    if validation_error:
        raise validation_error

    # restoring regular positional args
    parsed_known_args = tuple(parsed_kwargs.pop(arg) for arg in args_names[:positional_args_end])
    # restoring *args
    parsed_additional_args = parsed_kwargs.pop(var_args_name, ())
    # restoring **kwargs
    parsed_additional_kwargs = parsed_kwargs.pop(var_kwargs_name, {})

    return parsed_known_args, parsed_additional_args, parsed_kwargs, parsed_additional_kwargs


def parse_result(model, result):
    result, _fields, validation_error = validate_model(model, result)
    if validation_error:
        raise validation_error
    return result['__root__']


def prepare_models(
        wrapped: Wrapped,
        args_spec: ArgsSpec,
        config: Type[pydantic.BaseConfig] = None,
        validators: Dict[str, classmethod] = None,
        check_returns: bool = False
) -> Tuple[ModelType, Optional[ModelType]]:

    args_model = pydantic.create_model(
        model_name=getattr(wrapped, '__qualname__', 'callable') + '_args_model',
        __config__=config,
        __validators__=validators,
        **args_spec.field_definitions
    )

    args_model.__config__.extra = pydantic.Extra.forbid
    logging.debug(f'Created arguments model for {wrapped} with fields: {args_model.__fields__}')
    wrapped.__args_model__ = args_model

    if check_returns:
        class ReturnModel(pydantic.BaseModel):
            Config = config
            __annotations__ = {'__root__': wrapped.__annotations__['return']}

        logging.debug(f'Created returns model for {wrapped} with fields: {ReturnModel.__fields__}')
        wrapped.__returns_model__ = ReturnModel
        return args_model, ReturnModel

    wrapped.__returns_model__ = None
    return args_model, None
