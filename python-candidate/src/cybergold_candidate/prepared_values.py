"""Owned immutable JSON values with reusable exact content keys.

Mutable callers are captured by value, never memoized by object identity across
captures. Only frozen children can reuse their content keys. Explicit exports
and deepcopy return ordinary privately owned dictionaries/lists.
"""
from copy import deepcopy
import json


class ContentKey:
    def __init__(self, value):
        self.value = value
        self._hash = hash(value)

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        return isinstance(other, ContentKey) and self.value == other.value

    def __reduce__(self):
        # Python's string hash seed belongs to this process.
        return ContentKey, (self.value,)


def _readonly(*args, **kwargs):
    raise TypeError('Prepared observation is immutable; export a private copy to edit it')


class _Prepared:
    @property
    def content_key(self):
        if not hasattr(self, '_content_key'):
            self._content_key = exact_key(self, prepared=False)
        return self._content_key


class FrozenDict(dict, _Prepared):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _readonly

    def __deepcopy__(self, memo):
        return deepcopy(dict(self), memo)

    def __reduce__(self):
        return freeze, (dict(self),)


class FrozenList(list, _Prepared):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _readonly

    def __deepcopy__(self, memo):
        return deepcopy(list(self), memo)

    def __reduce__(self):
        return freeze, (list(self),)


def freeze(value, memo=None):
    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if not isinstance(value, (dict, list, tuple)):
        return deepcopy(value)
    memo = {} if memo is None else memo
    if id(value) in memo:
        return memo[id(value)]
    result = (FrozenDict({key: freeze(row, memo) for key, row in value.items()})
              if isinstance(value, dict) else FrozenList(freeze(row, memo) for row in value))
    memo[id(value)] = result
    result.derived = {}
    return result


def exact_key(value, *, prepared=True):
    """JSON distinctions including bool/int/float and ordered arrays.

    Dict keys use JSON's normal key conversion and sorting errors. Mutable
    roots are traversed afresh; their frozen coverage children are constant work.
    """
    if prepared and isinstance(value, (FrozenDict, FrozenList)):
        return value.content_key
    if isinstance(value, dict):
        return ContentKey(('object', tuple((_object_key(key), exact_key(value[key]))
                                          for key in sorted(value))))
    if isinstance(value, (list, tuple)):
        return ContentKey(('array', tuple(exact_key(row) for row in value)))
    if value is None:
        return ('null',)
    if isinstance(value, str):
        return 'string', value
    if isinstance(value, bool):
        return 'bool', value
    if isinstance(value, int):
        return 'int', int(value)
    return 'scalar', json.dumps(value, separators=(',', ':'))


def _object_key(key):
    if isinstance(key, str):
        return key
    if key is None:
        return 'null'
    if key is True:
        return 'true'
    if key is False:
        return 'false'
    if isinstance(key, (int, float)):
        return json.dumps(key)
    # Preserve JSON's normal error for unsupported object keys.
    json.dumps({key: None})
