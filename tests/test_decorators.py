import re
from typing import List, Any, Dict, Tuple

import pydantic
import pytest
from pydantic import ValidationError, BaseConfig, BaseModel

from got_it import got_it, ignore_it
from got_it.decorators import got_it_everywhere


def test_basic():
    @got_it
    def f(a: int, b: float, *args: int, **kwargs: int):
        return a, b, args, kwargs

    assert f('1', '1.6', z='3') == f(b='1.6', a='1', z='3') == (1, 1.6, (), {'z': 3})
    assert f('1', '2', '3', '4') == (1, 2, (3, 4), {})

    @got_it
    def f(a: int):
        return a

    with pytest.raises(ValidationError) as e:
        f(1, z=2)
    assert e.value.errors() == [{'loc': ('z',), 'msg': 'extra fields not permitted', 'type': 'value_error.extra'}]

    with pytest.raises(TypeError, match="No annotation or default value specified for argument 'a'"):
        @got_it
        def f(a):
            ...


def test_methods():
    class A:
        @got_it
        @classmethod
        def cls_m(cls, a: int, b: int, **kwargs):
            return a, b, kwargs

        @got_it
        def m(self, a: int, b: int, **kwargs):
            return a, b, kwargs

    a = A()
    assert a.cls_m('1', 2, z=3) == a.m('1', 2, z=3) == (1, 2, {'z': 3})


def test_classes():
    class B:
        @staticmethod
        def static_m(i: int):
            return i

    @got_it_everywhere(include_bases=True, exclude={'exclude_m'}, include={'__init__'})
    class A(B):
        def __init__(self, i: int):
            self.i = i
            self._b = None

        def m(self, i: int):
            return self, i

        @classmethod
        def class_m(cls, i: int):
            return cls, i

        @property
        def b(self):
            return self._b

        @b.setter
        def b(self, value: int):
            self._b = value

        @ignore_it
        def ignore_m(self, i: int):
            return i

        def exclude_m(self, i: int):
            return i

    a = A('1')
    assert a.i == 1
    assert a.m('1') == (a, 1)
    assert a.class_m('1') == (A, 1)
    assert a.static_m('1') == 1
    assert a.ignore_m('1') == '1'
    assert a.exclude_m('1') == '1'
    a.b = '1'
    assert a.b == 1

    class A:
        def __call__(self, i: int):
            return i

    a = got_it(A())
    assert a('2') == 2


def test_config():
    class MyConfig(BaseConfig):
        allow_population_by_field_name = True

    @got_it(config=MyConfig)
    def f(a: int, **kwargs):
        return a, kwargs

    MyConfig.extra = pydantic.Extra.forbid
    assert f.__args_model__.__config__.allow_population_by_field_name == MyConfig.allow_population_by_field_name
    assert f(1, z=2) == (1, {'z': 2})


def test_model_fields_equality():
    @got_it
    def f(a: int, b: List[float], *ints: int, c=2, z: Any = None, **bools: bool): ...

    class Model(BaseModel):
        a: int
        b: List[float]
        ints: Tuple[int, ...] = ()
        bools: Dict[str, bool] = {}
        c = 2
        z: Any = None

        class Config:
            extra = 'forbid'

    assert Model.__config__.__dict__ == f.__args_model__.__config__.__dict__

    def get_fields_params(fields):
        return {name: {'type': field.type_, 'default': field.default, 'required': field.required}
                for name, field in fields.items()}

    assert get_fields_params(Model.__fields__) == get_fields_params(f.__args_model__.__fields__)


def test_errors():
    with pytest.raises(TypeError, match=re.escape('__init__() takes 1 positional argument but 2 were given')):
        @got_it(BaseConfig)
        def f(a: int): ...

    with pytest.raises(TypeError, match="No annotation or default value specified for argument 'a'"):
        @got_it
        def f(a=None): ...

    @got_it
    def f(a: int, b=2): ...

    with pytest.raises(TypeError, match="got multiple values for argument 'a'"):
        f(1, a=1)

    with pytest.raises(TypeError, match='wrapping class is not supported, use `got_it_everywhere` instead'):
        @got_it(exclude=set(), include_bases=True)
        class A: ...
