# Got it!

# Pydantic now has similar decorator out of the box, you should stick with it.

### It's not a validator. It's better!

`got_it` is a tool built upon a pydantic to parse incoming arguments of a function


`average.py`
```python
import sys

from got_it import got_it


@got_it
def average(*numbers: float):
    return sum(numbers) / len(numbers)


if __name__ == '__main__':
    print(average(*sys.argv[1:]))
```
```bash
$ python average.py 1 2 4.6 10 9.4
5.4

$ python average.py not a number
Traceback (most recent call last):
    ...
pydantic.error_wrappers.ValidationError: 3 validation errors for average_args_model
numbers -> 0
  value is not a valid float (type=type_error.float)
numbers -> 1
  value is not a valid float (type=type_error.float)
numbers -> 2
  value is not a valid float (type=type_error.float)
```
