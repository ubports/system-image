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

"""Determine candidate images."""

__all__ = [
    'get_candidates',
    'get_downloads',
    ]


import os

from collections import deque
from resolver.config import config
from urllib.parse import urljoin


class _Chaser:
    def __init__(self):
        # Paths are represented by lists, so we need to listify each element
        # of the initial set of roots.
        self._paths = deque()

    def __iter__(self):
        while self._paths:
            yield self._paths.pop()

    def push(self, new_path):
        # new_path must be a list.
        self._paths.appendleft(new_path)


def get_candidates(index, build):
    """Calculate all the candidate upgrade paths.

    This function returns a list of candidate upgrades paths, from the
    current build number to the latest build available in the index
    file.

    Each element of this list of candidates is itself a list of `Image`
    objects, in the order that they should be applied to upgrade the
    device.

    The upgrade candidate chains are not sorted, ordered, or prioritized
    in any way.  They are simply the list of upgrades that will satisfy
    the requirements.  It is possible that there are no upgrade candidates if
    the device is already at the latest build, or if the device is at a build
    too old to update.

    :param index: The index of available upgrades.
    :type index: An `Index`
    :param build: The build version number that the device is currently at.
    :type build: str
    :return: list-of-lists of upgrade paths.  The empty list is returned if
        there are no candidate paths.
    """
    # Start by splitting the images into fulls and delta.  Throw out any full
    # updates which have a minimum version greater than our version.
    fulls = set()
    deltas = set()
    for image in index.images:
        if image.type == 'full':
            if getattr(image, 'minversion', 0) <= build:
                fulls.add(image)
        elif image.type == 'delta':
            deltas.add(image)
        else:
            # BAW 2013-04-30: log and ignore.
            raise AssertionError('unknown image type: {}'.format(image.type))
    # Load up the roots of candidate upgrade paths.
    chaser = _Chaser()
    # Each full version that is newer than our current version provides the
    # start of an upgrade path.
    for image in fulls:
        if image.version > build:
            chaser.push([image])
    # Each delta with a base that matches our version also provides the start
    # of an upgrade path.
    for image in deltas:
        if image.base == build:
            chaser.push([image])
    # Chase the back pointers from the deltas until we run out of newer
    # versions.  It's possible to push new paths into the chaser if we find a
    # fork in the road (i.e. two deltas with the same base).
    paths = list()
    for path in chaser:
        current = path[-1]
        while True:
            # Find all the deltas that have this step as their base.
            next_steps = [delta for delta in deltas
                          if delta.base == current.version]
            # If there is no next step, then we're done with this path.
            if len(next_steps) == 0:
                paths.append(path)
                break
            # If there's only one next step, append that to path and keep
            # going, with this step as the current image.
            elif len(next_steps) == 1:
                current = next_steps[0]
                path.append(current)
            # Otherwise, we have a fork.  Take one fork now and push the other
            # paths onto the chaser.
            else:
                current = next_steps.pop()
                for fork in next_steps:
                    new_path = path.copy()
                    new_path.append(fork)
                    chaser.push(new_path)
                path.append(current)
    return paths


def get_downloads(winner):
    """Return the list of files to download given the upgrade winner.

    Image traversal will stop after the first `bootme` flag is seen, so the
    list of files to download may not include all the files in the upgrade
    candidate.

    :param winner: The list of images for the winning candidate.
    :return: The list of file records describing the files to download.  Each
        file record is a dictionary as described in the index.json file and
        contains such information as the path to the signature file, the
        file's checksum and size, and its order.
    """
    for image in winner:
        for filerec in image.files:
            yield filerec
        if getattr(image, 'bootme', False):
            break
