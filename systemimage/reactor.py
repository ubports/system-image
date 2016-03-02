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

"""A D-Bus signal reactor class."""

import os
import logging

from gi.repository import GLib

log = logging.getLogger('systemimage')


# LP: #1240106 - We get intermittent and unreproducible TimeoutErrors in the
# DEP 8 when the default timeout is used.  It seems like cranking this up to
# 20 minutes makes the tests pass.  This must be some weird interaction
# between ubuntu-download-manager and the autopkgtest environment because a
# TimeoutError means we don't hear from u-d-m for 10 minutes... at all!  No
# signals of any kind.  It's possible this is related to LP: #1240157 in
# u-d-m, but as that won't likely get fixed for Saucy, this is a hack that
# allows the DEP 8 tests to increase the timeout and hopefully succeed.

OVERRIDE = os.environ.get('SYSTEMIMAGE_REACTOR_TIMEOUT')
TIMEOUT_SECONDS = (600 if OVERRIDE is None else int(OVERRIDE))


class Reactor:
    """A reactor base class for DBus signals."""

    def __init__(self, bus):
        self._bus = bus
        self._loop = None
        # Keep track of the GLib handles to the loop-quitting callback, and
        # all the signal matching callbacks.  Once the reactor run loop quits,
        # we want to remove all callbacks so they can't accidentally be called
        # again later.
        self._quitter = None
        self._signal_matches = []
        self._active_timeout = None
        self.timeout = TIMEOUT_SECONDS
        self.timed_out = False

    def _handle_signal(self, *args, **kws):
        # We've seen some activity from the D-Bus service, so reset our
        # timeout loop.
        self._reset_timeout()
        # Now dispatch the signal.
        signal = kws.pop('member')
        path = kws.pop('path')
        method = getattr(self, '_do_' + signal, None)
        if method is None:
            # See if there's a default catch all.
            method = getattr(self, '_default', None)
        if method is None:                          # pragma: no cover
            log.info('No handler for signal {}: {} {}', signal, args, kws)
        else:
            method(signal, path, *args, **kws)

    def _reset_timeout(self, *, try_again=True):
        if self._quitter is not None:
            GLib.source_remove(self._quitter)
            self._quitter = None
        if try_again:
            self._quitter = GLib.timeout_add_seconds(
                self._active_timeout, self._quit_with_error)

    def react_to(self, signal, object_path=None):
        signal_match = self._bus.add_signal_receiver(
            self._handle_signal,
            signal_name=signal,
            path=object_path,
            member_keyword='member',
            path_keyword='path',
            )
        self._signal_matches.append(signal_match)

    def schedule(self, method, milliseconds=50):
        GLib.timeout_add(milliseconds, method)

    def run(self, timeout=None):
        self._active_timeout = (self.timeout if timeout is None else timeout)
        self._loop = GLib.MainLoop()
        self._reset_timeout()
        self._loop.run()

    def quit(self):
        self._loop.quit()
        for match in self._signal_matches:
            match.remove()
        del self._signal_matches[:]
        self._reset_timeout(try_again=False)
        self._quitter = None
        self._active_timeout = None

    def _quit_with_error(self):
        self.timed_out = True
        self.quit()
