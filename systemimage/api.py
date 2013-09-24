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

"""DBus API mediator."""


__all__ = [
    'Mediator',
    'Update',
    ]


from systemimage.helpers import last_update_date
from systemimage.state import State
from threading import Event


class Update:
    """A representation of the available update."""

    def __init__(self, winners):
        self._winners = [] if winners is None else winners

    @property
    def is_available(self):
        return len(self._winners) > 0

    @property
    def size(self):
        total_size = 0
        for image in self._winners:
            total_size += sum(filerec.size for filerec in image.files)
        return total_size

    @property
    def descriptions(self):
        return [image.descriptions for image in self._winners]

    @property
    def version(self):
        try:
            return str(self._winners[-1].version)
        except IndexError:
            # No winners.
            return ''

    @property
    def last_update_date(self):
        return last_update_date()


class Mediator:
    """This is the DBus API mediator.

    It essentially implements the entire DBus API, but at a level below the
    mechanics of DBus.  Methods of this class are hooked directly into the
    DBus layer to satisfy that interface.
    """

    def __init__(self):
        self._state = State()
        self._cancel = Event()
        self._update = None

    def cancel(self):
        self._state.downloader.cancel()

    def check_for_update(self):
        """Is there an update available for this machine?

        :return: Flag indicating whether an update is available or not.
        :rtype: bool
        """
        if self._update is None:
            self._state.run_until('download_files')
            self._update = Update(self._state.winner)
        return self._update

    def download(self):
        """Download the available update."""
        self._state.run_until('reboot')

    def reboot(self):
        """Issue the reboot."""
        # Transition through all remaining states.
        list(self._state)
