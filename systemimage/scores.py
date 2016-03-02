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

"""Upgrade policy decisions.

Choose which upgrade path to use based on the available candidates.
"""

__all__ = [
    'Scorer',
    'WeightedScorer',
    ]


import logging

from itertools import count
from systemimage.helpers import MiB, phased_percentage


log = logging.getLogger('systemimage')
COLON = ':'


class Scorer:
    """Abstract base class providing an API for candidate selection."""

    def choose(self, candidates, channel):
        """Choose the candidate upgrade paths.

        Lowest score wins.

        :param candidates: A list of lists of image records needed to upgrade
            the device from the current version to the latest version, sorted
            in order from oldest verson to newest.
        :type candidates: list of lists
        :param channel: The channel being upgraded to.  This is used in the
            phased update calculate.
        :type channel: str
        :return: The chosen path.
        :rtype: list
        """
        if len(candidates) == 0:
            log.debug('No candidates, so no winner')
            return []
        # We want to zip together the score for each candidate path, plus the
        # candidate path, so that when we sort the sequence, we'll always get
        # the lowest scoring upgrade path first.  The problem is that when two
        # paths have the same score, sorted()'s comparison will find the first
        # element of the tuple is the same and fall back to the second item.
        # If that item is a list of Image objects, then it will try to compare
        # Image objects, which are not comparable.
        #
        # We solve this by zipping in a second element which is guaranteed to
        # be a monotomically increasing integer.  Thus if two paths score the
        # same, we'll just end up picking the first one we saw, and comparison
        # will never fall back to the list of Images.
        #
        # Be sure that after all is said and done we return the list of Images
        # though!
        scores = sorted(zip(self.score(candidates), count(), candidates))
        # Calculate the phase percentage for the device.  Use the highest
        # available build number as input into the random seed.
        max_target_number = -1
        for score, i, path in scores:
            # The last image will be the target image.
            assert len(path) > 0, 'Empty upgrade candidate path?'
            max_target_number = max(max_target_number, path[-1].version)
        assert max_target_number != -1, 'No max target version?'
        device_percentage = phased_percentage(channel, max_target_number)
        log.debug('Device phased percentage: {}%'.format(device_percentage))
        log.debug('{} path scores:'.format(self.__class__.__name__))
        # Log the candidate paths, their scores, and their phases.
        for score, i, path in reversed(scores):
            log.debug('\t[{:4d}] -> {} ({}%)'.format(
                score,
                COLON.join(str(image.version) for image in path),
                (path[-1].phased_percentage if len(path) > 0 else '--')
                ))
        for score, i, path in scores:
            image_percentage = path[-1].phased_percentage
            # An image percentage of 0 means that it's been pulled.
            if image_percentage > 0 and device_percentage <= image_percentage:
                return path
        # No upgrade path.
        return []

    def score(self, candidates): # pragma: no cover
        """Like `choose()` except returns the candidate path scores.

        Subclasses are expected to override this method.

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
    """Use the following inputs and weights. Lowest score wins.

    reboots - Look at the entire path and add 100 for every extra reboot
        required.  The implicit end-of-update reboot is not counted.

    total download size - add 1 for every 1MiB over the smallest image.

    destination build number - absolute value of the total distance from the
        highest version number + 9000.

    Examples:

    - Path A requires three extra reboots, is the smallest total
      download and leaves you at the highest available version.
      Score: 300

     - Path B requires one extra reboot, but is 100MiB bigger and leaves
       you at the highest available version.  Score: 200

     - Path C requires no extra reboots, but is 400MiB bigger and leaves
       you at 20130303 instead of the highest 20130304.  Score: 401

    Path B wins.
    """
    def score(self, candidates):
        # Iterate over every path, calculating the total download size of the
        # path, the number of extra reboots required, and the destination
        # build number.  Remember the smallest size seen and highest build
        # number.
        max_build = 0
        min_size = None
        candidate_data = []
        for path in candidates:
            build = path[-1].version
            size = 0
            for image in path:
                image_size = sum(filerec.size for filerec in image.files)
                size += image_size
            reboots = sum(1 for image in path
                          if getattr(image, 'bootme', False))
            candidate_data.append((build, size, reboots, path))
            max_build = max(build, max_build)
            min_size = (size if (min_size is None or size < min_size)
                        else min_size)
        # Score the candidates.  Any path that doesn't leave you at the
        # maximum build number gets a ridiculously high score so it won't
        # possibly be chosen.
        scores = []
        for build, size, reboots, path in candidate_data:
            score = (100 * reboots) + ((size - min_size) // MiB)
            # If the path does not leave you at the maximum build number, add
            # a ridiculously high value which essentially prevents that
            # candidate path from winning.
            distance = max_build - build
            score += (9000 * distance) + distance
            scores.append(score)
        return scores
