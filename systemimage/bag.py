# Copyright (C) 2013-2016 Canonical Ltd.
# Author: Barry Warsaw <barry@ubuntu.com>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""The Bag class."""

__all__ = [
    'Bag',
    ]


import keyword

from collections import defaultdict


COMMASPACE = ', '


def default():
    def identity(value):
        return value
    return identity


def make_converter(original):
    converters = defaultdict(default)
    if original is not None:
        converters.update(original)
    return converters


class Bag:
    # NOTE: This class's methods share a namespace with the possible
    # configuration variable names in the various sections.  Thus no variable
    # in any section can be named `update`, `keys`, or `get`.  They also can't
    # be named like any of the non-public methods, but that's usually not a
    # problem.  Ideally, we'd name the methods part of the reserved namespace,
    # but it seems like a low tech debt for now.
    def __init__(self, *, converters=None, **kws):
        self._converters = make_converter(converters)
        self.__original__ = {}
        self.__untranslated__ = {}
        self._load_items(kws)

    def update(self, *, converters=None, **kws):
        if converters is not None:
            self._converters.update(converters)
        self._load_items(kws)

    def _load_items(self, kws):
        for key, value in kws.items():
            self.__original__[key] = value
            safe_key, converted_value = self._normalize_key_value(key, value)
            self.__untranslated__[key] = converted_value
            # BAW 2013-04-30: attribute values *must* be immutable, but for
            # now we don't enforce this.  If you set or delete attributes, you
            # will probably break things.
            self.__dict__[safe_key] = converted_value

    def _normalize_key_value(self, key, value):
        value = self._converters[key](value)
        key = key.replace('-', '_')
        if keyword.iskeyword(key):
            key += '_'
        return key, value

    def __repr__(self): # pragma: no cover
        return '<Bag: {}>'.format(COMMASPACE.join(sorted(
            key for key in self.__dict__ if not key.startswith('_'))))

    def __setitem__(self, key, value):
        if key in self.__original__:
            raise ValueError('Attributes are immutable: {}'.format(key))
        safe_key, converted_value = self._normalize_key_value(key, value)
        self.__dict__[safe_key] = converted_value
        self.__untranslated__[key] = converted_value

    def __getitem__(self, key):
        return self.__untranslated__[key]

    def keys(self):
        for key in self.__untranslated__:
            if not key.startswith('_'):
                yield key

    def get(self, key, default=None):
        if key in self.__dict__:
            return self.__dict__[key]
        return default

    def __iter__(self):
        yield from self.keys()

    # Pickle protocol.

    def __getstate__(self):
        # We don't need to pickle the converters, because for all practical
        # purposes, those are only used when the Bag is instantiated.
        return (self.__original__,
                {key: value for key, value in self.__dict__.items()
                 if not key.startswith('_')})

    def __setstate__(self, state):
        original, values = state
        self.__original__ = original
        self._converters = None
        for key, value in values.items():
            self.__dict__[key] = value
