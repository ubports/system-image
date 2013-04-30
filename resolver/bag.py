# Copyright (C) 2013 Canonical Ltd.
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


COMMASPACE = ', '


class Bag:
    def __init__(self, **kws):
        self.__original__ = {}
        for key, value in kws.items():
            self.__original__[key] = value
            # Replace problematic characters, e.g. ubuntu-rootfs
            safe_key = key.replace('-', '_')
            if keyword.iskeyword(safe_key):
                safe_key += '_'
            # BAW 2013-04-30: attribute values *must* be immutable, but for
            # now we don't enforce this.  If you set or delete attributes, you
            # will probably break things.
            self.__dict__[safe_key] = value

    def __repr__(self):
        return '<Bag: {}>'.format(COMMASPACE.join(sorted(
            key for key in self.__dict__ if key != '__original__')))
