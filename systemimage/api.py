# Copyright (C) 2013-2015 Canonical Ltd.
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


import logging

from systemimage.apply import factory_reset
from systemimage.state import State
from unittest.mock import patch


log = logging.getLogger('systemimage')


class Update:
    """A representation of the available update."""

    def __init__(self, winners=None, error=''):
        self._winners = [] if winners is None else winners
        self.error = error

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


class Mediator:
    """This is the DBus API mediator.

    It essentially implements the entire DBus API, but at a level below the
    mechanics of DBus.  Methods of this class are hooked directly into the
    DBus layer to satisfy that interface.
    """

    def __init__(self, callback=None):
        self._state = State()
        self._update = None
        self._callback = callback

    def __repr__(self): # pragma: no cover
        return '<Mediator at 0x{:x} | State at 0x{:x}>'.format(
            id(self), id(self._state))

    def cancel(self):
        self._state.downloader.cancel()

    def pause(self):
        self._state.downloader.pause()

    def resume(self):
        self._state.downloader.resume()

    def check_for_update(self):
        """Is there an update available for this machine?

        :return: Flag indicating whether an update is available or not.
        :rtype: bool
        """
        if self._update is None:
            try:
                self._state.run_until('download_files')
            except Exception as error:
                # Rather than letting this percolate up, eventually reaching
                # the GLib main loop and thus triggering apport, Let's log the
                # error and set the relevant information in the class.
                log.exception('check_for_update failed')
                self._update = Update(error=str(error))
            else:
                self._update = Update(self._state.winner)
        return self._update

    def download(self):
        """Download the available update."""
        # We only want callback progress during the actual download.
        with patch.object(self._state.downloader, 'callback', self._callback):
            self._state.run_until('apply')

    def apply(self):
        """Apply the update."""
        # Transition through all remaining states.
        list(self._state)

    def factory_reset(self):
        factory_reset()
