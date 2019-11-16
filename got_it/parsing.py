import inspect
from functools import partial
from typing import Type

import pydantic

from .args import ArgsSpec, restore_args
from .typing import Wrapped, ParsedArgs, TupleAny, DictStrAny

# in pydantic 1.0 validate_model doesn't have attr raise_exc and always returns exception
if 'raise_exc' in inspect.getfullargspec(pydantic.validate_model).args:
    validate_model = partial(pydantic.validate_model, raise_exc=False)
else:
    validate_model = pydantic.validate_model

RETURN_KEY = 'returns'


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
        known_args_names=set(args_names),
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
        if name in all_kwargs:  # need to manually check that, otherwise kwargs may be overwritten silently
            f_name = getattr(wrapped, '__qualname__', wrapped)
            raise TypeError(f"'{f_name}' got multiple values for argument '{name}'")
        known_kwargs[name] = arg

    parsed_kwargs, _fields, validation_error = validate_model(model, known_kwargs)
    if validation_error:
        raise validation_error

    # restoring regular positional args
    parsed_known_args = tuple([parsed_kwargs.pop(arg) for arg in args_names[:positional_args_end]])
    # restoring *args
    parsed_additional_args = parsed_kwargs.pop(var_args_name, ())
    # restoring **kwargs
    parsed_additional_kwargs = parsed_kwargs.pop(var_kwargs_name, {})

    return parsed_known_args, parsed_additional_args, parsed_kwargs, parsed_additional_kwargs


def parse_result(model, result):
    result, _fields, validation_error = validate_model(model, {RETURN_KEY: result})
    if validation_error:
        raise validation_error
    return result[RETURN_KEY]
