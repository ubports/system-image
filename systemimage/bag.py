# Copyright (C) 2013-2014 Canonical Ltd.
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
    def __init__(self, *, converters=None, **kws):
        self._converters = make_converter(converters)
        self.__original__ = {}
        self.__untranslated__ = {}
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

    def __repr__(self):
        return '<Bag: {}>'.format(COMMASPACE.join(sorted(
            key for key in self.__dict__ if not key.startswith('_'))))

    def __setitem__(self, key, value):
        if key in self.__original__:
            raise ValueError('Attributes are immutable: {}'.format(key))
        self.__original__[key] = value
        safe_key, converted_value = self._normalize_key_value(key, value)
        self.__dict__[safe_key] = converted_value
        self.__untranslated__[key] = converted_value

    def __getitem__(self, key):
        return self.__untranslated__[key]

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
