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

"""A D-Bus signal reactor class."""

import logging

from gi.repository import GLib

log = logging.getLogger('systemimage')


TIMEOUT_SECONDS = 120


class Reactor:
    """A reactor base class for DBus signals."""

    def __init__(self, bus):
        self._bus = bus
        self._loop = None
        self._quitters = []
        self._signal_matches = []
        self.timeout = TIMEOUT_SECONDS

    def _handle_signal(self, *args, **kws):
        signal = kws.pop('member')
        path = kws.pop('path')
        method = getattr(self, '_do_' + signal, None)
        if method is None:
            # See if there's a default catch all.
            method = getattr(self, '_default', None)
        if method is None:
            log.info('No handler for signal {}: {} {}', signal, args, kws)
        else:
            method(signal, path, *args, **kws)

    def react_to(self, signal):
        signal_match = self._bus.add_signal_receiver(
            self._handle_signal, signal_name=signal,
            member_keyword='member',
            path_keyword='path')
        self._signal_matches.append(signal_match)

    def schedule(self, method, milliseconds=50):
        GLib.timeout_add(milliseconds, method)

    def run(self, timeout=None):
        timeout = (self.timeout if timeout is None else timeout)
        self._loop = GLib.MainLoop()
        source_id = GLib.timeout_add_seconds(timeout, self.quit)
        self._quitters.append(source_id)
        self._loop.run()

    def quit(self):
        self._loop.quit()
        for match in self._signal_matches:
            match.remove()
        del self._signal_matches[:]
        for source_id in self._quitters:
            GLib.source_remove(source_id)
        del self._quitters[:]
