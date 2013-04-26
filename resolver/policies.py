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

"""Upgrade policy decisions.

Choose which upgrade path to use based on the available candidates.
"""

__all__ = [
    'ByDownloadSize',
    'Policy',
    ]


class Policy:
    """Abstract base class providing an API for candidate selection."""

    def choose(self, candidates):
        """Choose an upgrade path from the set of candidate paths.

        Subclasses are expected to override this method.

        :param candidates: A list of lists of image records needed to upgrade
            the device from the current version to the latest version, sorted
            in order from oldest verson to newest.
        :type candidates: list of lists
        :return: The upgrade path matching the class's defined policy.
        :rtype: list
        """
        raise NotImplementedError


class ByDownloadSize(Policy):
    def choose(self, candidates):
        if len(candidates) == 0:
            return []
        sizes = []
        for path in candidates:
            size = sum(image.size for image in path)
            sizes.append((size, path))
        # The first item of the sorted sizes will be the smallest one in terms
        # of total download size.  The second item of that list will be the
        # candidate paths.
        smallest = sorted(sizes)[0][1]
        return smallest
