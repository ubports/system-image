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

"""Images are like Bags but are hashable and sortable."""


__all__ = [
    'Image',
    ]


from systemimage.bag import Bag

COMMASPACE = ', '


class Image(Bag):
    def __init__(self, **kws):
        converters = {'phased-percentage': int}
        super().__init__(converters=converters, **kws)

    def __hash__(self):
        # BAW 2013-04-30: We don't currently enforce immutability of attribute
        # values.  See Bag.__init__().
        #
        # Full images must be unique on the version, but delta images are
        # unique on the version and base.  We need to turn these two values
        # into a hash of no more than 32 bits.  This is because Python's
        # built-in hash() method truncates __hash__()'s return value to
        # Py_ssize_t which on the phone hardware (and i386 as in the buildds)
        # is 32 bits.
        #
        # You can verifiy this with the following bit of Python:
        #
        # $ python3 -c "from ctypes import *; print(sizeof(c_ssize_t))"
        #
        # Use a base of 0 for full images.
        base = self.base if self.type == 'delta' else 0
        assert ((0 <= base < (1 << 16)) and (0 <= self.version < (1 << 16))), (
            '16 bit unsigned version numbers only')
        # LP: #1218612 introduces a new version number regime, starting
        # sequentially at 1.  We still have the 32 bit limit on hashes, but
        # now we don't have to play games with the content, giving us 65k new
        # versions before we have to worry about running out of bits.  We
        # still have to fit two version numbers (version and base for deltas)
        # into those 32 bits, thus version numbers bigger than 16 bits are not
        # supported.  Still, even if we release 10 images every day, that
        # gives us nearly 17 years of running room.  I sure hope we'll have 64
        # bit phones by then.
        return (self.version << 16) + base

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self): # pragma: no cover
        return '<Image: {}>'.format(COMMASPACE.join(sorted(
            key for key in self.__dict__ if not key.startswith('_'))))

    @property
    def phased_percentage(self):
        return self.__untranslated__.get('phased-percentage', 100)

    @property
    def version_detail(self):
        return self.__untranslated__.get('version_detail', '')
