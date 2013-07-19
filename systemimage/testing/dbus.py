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

"""Helpers for the DBus service when run with --testing."""

__all__ = [
    'instrument',
    ]


import os

from functools import partial
from systemimage.testing.helpers import test_data_path
from unittest.mock import patch
from urllib.request import urlopen


SPACE = ' '


def instrument(config, stack):
    """Instrument the system for testing."""
    # The testing infrastructure requires that the built-in downloader
    # accept self-signed certificates.  We have to invoke the context
    # manager here so that the function actually gets patched.
    stack.enter_context(
        patch('systemimage.download.urlopen',
              partial(urlopen, cafile=test_data_path('cert.pem'))))
    # Patch the subprocess call to write the reboot command to a log
    # file which the testing parent process can open and read.
    def safe_reboot(*args, **kws):
        path = os.path.join(
            config.updater.cache_partition, 'reboot.log')
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write(SPACE.join(args[0]).strip())
    stack.enter_context(
        patch('systemimage.reboot.check_call', safe_reboot))
