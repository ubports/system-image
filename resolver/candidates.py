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
    ]


from operator import attrgetter


def _scan(images, content, current_version, target_version):
    """Scan the list of images looking for upgrade paths."""
    # BAW 2013-04-24: No doubt we can make this more efficient later.  Let's
    # get it *right* first.
    starting_points = []
    for image in images:
        if image.content == content and image.version == target_version:
            starting_points.append(image)
    candidates = []
    for here in starting_points:
        path = []
        while True:
            if here.version == current_version:
                break
            path.append(here)
            if here.type == 'full':
                # We should never have to go back farther than at least one
                # monthly, i.e. full update.
                break
            # Deltas must have a 'base' attribute.
            base = here.base
            # If we're already at the base image version, we're done.
            if current_version == base:
                break
            for image in images:
                if image.content == content and image.version == base:
                    here = image
                    break
            else:
                # The base image could not be found, but we're not at the
                # current version.  What do we do?
                raise ValueError('Base image not found: {}'.format(base))
        if len(path) > 0:
            candidates.append(list(reversed(path)))
    # We want the candidates sorted in order from oldest to newest.
    return candidates


def get_candidates(index, ubuntu_version=None, android_version=None):
    """Calculate all the candidate upgrade paths.

    This function returns a 2-tuple where the first element describes the list
    of candidate upgrades for the Ubuntu side, and the second one describes
    the list of candidate upgrades for the Android side.

    Each of these individual lists is itself a list of image records.  Each of
    these is a chain of updates from the latest image version backward to the
    current image version.

    The upgrade candidate chainsy are not sorted, ordered, or prioritized in
    any way.  They are simply the list of upgrades that will satisfy the
    requirements.  It is possible that there are no chains for Ubuntu or
    Android if they are already at the latest version.  In this case, the
    lists will be empty.
    """
    # If there are no bundles, then there's nothing to do.
    if len(index.bundles) == 0:
        return [], []
    # Sort the available bundles by 'version' key and take the highest one.
    sorted_bundles = sorted(index.bundles, key=attrgetter('version'))
    # The last element of the list will be the highest version.
    newest_bundle = sorted_bundles.pop()
    # Sanity check that that there is only one bundle at this version.  It is
    # an error in the data if there is more than one.
    if (len(sorted_bundles) > 0
        and sorted_bundles[-1].version == newest_bundle.version):
        # BAW 2013-04-24: Perhaps this should log the problem and continue?
        raise ValueError('Duplicate bundle version: {}'.format(
            newest_bundle.version))
    if ubuntu_version is None:
        ubuntu_candidates = []
    else:
        ubuntu_candidates = _scan(
            index.images, 'ubuntu-rootfs',
            ubuntu_version, newest_bundle.images.ubuntu_rootfs)
    if android_version is None:
        android_candidates = []
    else:
        android_candidates = _scan(
            index.images, 'android',
            android_version, newest_bundle.images.android)
    return ubuntu_candidates, android_candidates
