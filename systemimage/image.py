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

"""Images are like Bags but are hashable and sortable."""


__all__ = [
    'Image',
    ]


from systemimage.bag import Bag

# The era starts in 2013.
ERA = 2013
COMMASPACE = ', '


def _old_hash(version):
    # Turn the old YYYYMMXX version numbers into 16 bit values, using the
    # following observations:
    #
    # * Assume none of this will matter 16 years from now (i.e. in 2029 ;)
    # * The middle two digits of the version number are a month, so we
    #   only need 4 bits (for months 0-11).
    # * We need 7 bits for the builds-per-month last two digits since the
    #   spec leaves room for 0-99 builds per month.
    #
    # But that's cool because a) gives of 4 bits, b) gives us 4 bits, and
    # c) gives us 7 bits for a total of 15 bits.  Double that (since the
    # hash has to support two version numbers for deltas) and that gives
    # us 30 bits.  Woo hoo!  2 bits to spare.
    #
    # Short-circuit for when the version number is 0.
    if version == 0:
        return 0
    # Split the version number up into years-since-era, month, and
    # builds-per-month.  BpM is 0-99.
    remainder, bpm = divmod(version, 100)
    year, month = divmod(remainder, 100)
    yse = year - ERA
    assert yse < 16, 'years since era breaks hash: {}'.format(yse)
    # Months count from 1 in the spec, but that doesn't affect the hash.
    assert month <= 12, 'month is out of spec: {}'.format(month)
    # 00-99 builds per month.
    assert bpm < 100, 'builds-per-month is out of spec: {}'.format(bpm)
    # For no particular reason, we'll save the extra bit in the least
    # significant position.
    return (yse << 12) + (month << 8) + (bpm << 1)


def _new_hash(version):
    # LP: #1218612 introduces a new version number regime, starting
    # sequentially at 1.  We still have the 32 bit limit on hashes, but now we
    # don't have to play games with the content, giving us 65k new versions
    # before we have to worry about running out of bits.  We still have to fit
    # two version numbers (version and base for deltas) into those 32 bits,
    # thus version numbers bigger than 16 bits are not supported.  Still, even
    # if we release 10 images every day, that gives us nearly 17 years of
    # running room.  I sure hope we'll have 64 bit phones by then.
    assert 0 <= version < (1 << 16), '16 bit unsigned version numbers only'
    return version


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
        # Which version number regime should we use.  We have to assume that
        # there won't be a version in one scheme and a base in another.
        if self.version < 20000000:
            # New regime.
            assert base < 20000000, 'Mixed version regime detected'
            hash_function = _new_hash
        else:
            assert base >= 20000000 or base == 0, (
                'Mixed version regime detected')
            hash_function = _old_hash
        return (hash_function(self.version) << 16) + hash_function(base)

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return '<Image: {}>'.format(COMMASPACE.join(sorted(
            key for key in self.__dict__ if not key.startswith('_'))))

    @property
    def phased_percentage(self):
        return self.__untranslated__.get('phased-percentage', 100)
