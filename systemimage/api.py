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
    'Cancel',
    'Mediator',
    'Update',
    ]


from systemimage.config import config
from systemimage.state import State
from threading import Event


class Cancel(BaseException):
    """Raised to cancel the big download."""


class Update:
    """A representation of the available update."""

    def __init__(self, winners):
        self._winners = [] if winners is None else winners

    def __bool__(self):
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
            return self._winners[-1].version
        except IndexError:
            # No winners.
            return 0


class Mediator:
    """This is the DBus API mediator.

    It essentially implements the entire DBus API, but at a level below the
    mechanics of DBus.  Methods of this class are hooked directly into the
    DBus layer to satisfy that interface.
    """

    def __init__(self, *, pending_cb=None, ready_cb=None):
        self._state = State(self._check_canceled)
        self._cancel = Event()
        self._update = None
        # Callback called when check_for_update() finds an update available.
        self._pending_cb = pending_cb
        # Callback called when complete_update() is done.
        self._ready_cb = ready_cb

    def _check_canceled(self, url, dst, bytes_read, size):
        if self._cancel.is_set():
            raise Cancel

    def get_build_number(self):
        return config.build_number

    def cancel(self):
        self._cancel.set()

    def check_for_update(self):
        """Is there an update available for this machine?

        :return: Flag indicating whether an update is available or not.
        :rtype: bool
        """
        if self._update is None:
            self._state.run_thru('calculate_winner')
            self._update = Update(self._state.winner)
            if self._update and self._pending_cb is not None:
                self._pending_cb()
        return self._update

    def complete_update(self):
        """Complete the update."""
        self._state.run_until('reboot')
        if self._ready_cb is not None:
            self._ready_cb()

    def reboot(self):
        """Issue the reboot."""
        list(self._state)
