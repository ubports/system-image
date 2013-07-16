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

"""Test the SystemImage dbus service."""

__all__ = [
    'TestDBus',
    ]


import dbus
import unittest

from contextlib import ExitStack
from systemimage.testing.dbus import Controller


_controller = None
_stack = ExitStack()


def setUpModule():
    global _controller
    _controller = Controller()
    _stack.callback(_controller.shutdown)
    _controller.start()
    if not _controller.is_runnable:
        _stack.close()
        _controller = None


def tearDownModule():
    global _controller
    _stack.close()
    _controller = None


@unittest.skipUnless(_controller is not None, 'No test controller available')
class TestDBus(unittest.TestCase):
    """Test the SystemImage dbus service."""

    def setUp(self):
        self.session_bus = dbus.SessionBus()
