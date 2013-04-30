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


from resolver.bag import Bag

# The smallest shift that can hold the 8 digit binary date stamp.
SHIFT = 2 ** 5


class Image(Bag):
    def __hash__(self):
        # BAW 2013-04-30: We don't currently enforce immutability of attribute
        # values.  See Bag.__init__().
        #
        # Full images must be unique on the version, but delta images are
        # unique on the version and base.  Combine them by shifting the image
        # version into the high bits and adding the base version, using a base
        # of 0 for full images.
        base = self.base if self.type == 'delta' else 0
        return (self.version << SHIFT) + base

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __ne__(self, other):
        return not self.__eq__(other)
