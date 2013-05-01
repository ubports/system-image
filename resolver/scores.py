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
    'Scorer',
    'WeightedScorer',
    ]


MiB = 2 ** 20


class Scorer:
    """Abstract base class providing an API for candidate selection."""

    def choose(self, candidates):
        """Choose the candidate upgrade paths.

        Subclasses are expected to override this method.

        Lowest score wins.

        :param candidates: A list of lists of image records needed to upgrade
            the device from the current version to the latest version, sorted
            in order from oldest verson to newest.
        :type candidates: list of lists
        :return: The chosen path.
        :rtype: list
        """
        if len(candidates) == 0:
            return []
        return sorted(zip(self.score(candidates), candidates))[0][1]

    def score(self, candidates):
        """Like `choose()` except returns the candidate path scores.

        :param candidates: A list of lists of image records needed to upgrade
            the device from the current version to the latest version, sorted
            in order from oldest verson to newest.
        :type candidates: list of lists
        :return: The list of path scores.  This will be the same size as the
            list of paths in `candidates`.
        :rtype: list
        """
        raise NotImplementedError


class WeightedScorer(Scorer):
    """Use the following inputs and weights.

    Lowest score wins.

    reboots - Look at the entire path and add 100 for every extra reboot
        required.  The implicit end-of-update reboot is not counted.

    total download size - add 1 for every 1MiB over the smallest image.

    destination build number - absolute value of the total distance from the
        highest version number.

    Examples:

    - Path A requires two extra reboots, is the smallest total download and
      leaves you at the higest available version.  Score: 200

    - Path B requires one extra reboot, but is 100MiB bigger and leaves you at
      the highest available version.  Score: 100

    - Path C requires no extra reboots, but is 200MiB bigger and leaves you at
      20130200 instead of the highest 20130304.  Score: 304

    Path B wins.
    """
    def score(self, candidates):
        # Iterate over every path, calculating the total download size of the
        # path, the number of extra reboots required, and the destination
        # build number.  Remember the smallest size seen and highest build
        # number.
        max_build = 0
        min_size = -1
        candidate_data = []
        for path in candidates:
            build = path[-1].version
            size = 0
            for image in path:
                image_size = sum(filename.size for filename in image.files)
                size += image_size
            reboots = sum(1 for image in path
                          if getattr(image, 'bootme', False))
            candidate_data.append((build, size, reboots, path))
            max_build = build if build > max_build else max_build
            min_size = size if size < min_size else min_size
        # Score the candidates, building the return list-of-tuples.
        scores = []
        for build, size, reboots, path in candidate_data:
            score = ((100 * reboots) +
                     ((size - min_size) // MiB) +
                     max_build - build)
            scores.append(score)
        return scores
