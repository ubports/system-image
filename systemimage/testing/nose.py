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

"""Nose plugin for testing."""

__all__ = [
    'SystemImagePlugin',
    ]


import re
import sys

from dbus.mainloop.glib import DBusGMainLoop
from nose.plugins import Plugin
from systemimage.logging import initialize
from systemimage.testing.helpers import configuration


class SystemImagePlugin(Plugin):
    enabled = True

    @configuration
    def begin(self):
        DBusGMainLoop(set_as_default=True)
        # Count verbosity.  There might be a better way to do this through
        # nose's command line option handling.
        verbosity = 0
        for arg in sys.argv[1:]:
            mo = re.match('^-(?P<verbose>v+)$', arg)
            if mo:
                verbosity += len(mo.group('verbose'))
        initialize(verbosity=verbosity)
