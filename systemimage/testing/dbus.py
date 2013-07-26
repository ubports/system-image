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
    'get_service',
    'instrument',
    ]


import os
import time

from dbus.service import method
from functools import partial
from systemimage.api import Mediator
from systemimage.config import config
from systemimage.dbus import Service
from systemimage.helpers import makedirs
from systemimage.testing.helpers import test_data_path
from unittest.mock import patch
from urllib.request import urlopen


SPACE = ' '
SIGNAL_DELAY_SECS = 5


class _ActionLog:
    def __init__(self, filename):
        makedirs(config.updater.cache_partition)
        self._path = os.path.join(config.updater.cache_partition, filename)

    def write(self, *args, **kws):
        with open(self._path, 'w', encoding='utf-8') as fp:
            fp.write(SPACE.join(args[0]).strip())


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
    safe_reboot = _ActionLog('reboot.log')
    stack.enter_context(
        patch('systemimage.reboot.check_call', safe_reboot.write))
    stack.enter_context(
        patch('systemimage.device.check_output', return_value='nexus7'))


class _LiveTestableService(Service):
    """For testing purposes only."""

    @method('com.canonical.SystemImage')
    def Reset(self):
        self._api = Mediator()
        self._checking = False
        self._completing = False
        self._rebootable = True


class _NoUpdateService(Service):
    """A static, 'no update is available' service."""

    @method('com.canonical.SystemImage', out_signature='i')
    def BuildNumber(self):
        return 42

    def _check_for_update(self):
        time.sleep(SIGNAL_DELAY_SECS)
        self.UpdateAvailableStatus(False)
        return False

    @method('com.canonical.SystemImage')
    def Reset(self):
        pass


class _UpdateSuccessService(Service):
    """A static, 'update available' service."""

    def __init__(self, bus, object_path, loop):
        super().__init__(bus, object_path, loop)
        self._canceled = False

    @method('com.canonical.SystemImage', out_signature='i')
    def BuildNumber(self):
        return 42

    def _check_for_update(self):
        time.sleep(SIGNAL_DELAY_SECS)
        self.UpdateAvailableStatus(True)
        return False

    @method('com.canonical.SystemImage')
    def Cancel(self):
        self._canceled = True
        self.Canceled()

    @method('com.canonical.SystemImage', out_signature='x')
    def GetUpdateSize(self):
        return 1337 * 1024

    @method('com.canonical.SystemImage', out_signature='i')
    def GetUpdateVersion(self):
        return 44

    @method('com.canonical.SystemImage', out_signature='aa{ss}')
    def GetDescriptions(self):
        return [
            {'description': 'Ubuntu Edge support',
             'description-fr': "Support d'Ubuntu Edge",
             'description-en': 'Initialise your Colour',
             'description-en_US': 'Initialize your Color',
            },
            {'description': 'Flipped container with 200% faster boot'},
            ]

    def _complete_update(self):
        time.sleep(SIGNAL_DELAY_SECS)
        if not self._canceled:
            self.ReadyToReboot()
        return False

    @method('com.canonical.SystemImage')
    def Reboot(self):
        if not self._canceled:
            # The actual reboot is mocked to write a reboot log, so go ahead
            # and call it.  The client will check the log.
            config.hooks.reboot().reboot()

    @method('com.canonical.SystemImage')
    def Reset(self):
        self._canceled = False
        self._completing = False
        self._checking = False


class _UpdateFailedService(_UpdateSuccessService):
    def _complete_update(self):
        time.sleep(SIGNAL_DELAY_SECS)
        if not self._canceled:
            self.UpdateFailed()
        return False

    @method('com.canonical.SystemImage')
    def Reboot(self):
        if not self._canceled:
            self.UpdateFailed()


def get_service(testing_mode, session_bus, object_path, loop):
    """Return the appropriate service class for the testing mode."""
    if testing_mode == 'live':
        ServiceClass = _LiveTestableService
    elif testing_mode == 'no-update':
        ServiceClass = _NoUpdateService
    elif testing_mode == 'update-success':
        ServiceClass = _UpdateSuccessService
    elif testing_mode == 'update-failed':
        ServiceClass = _UpdateFailedService
    else:
        raise RuntimeError('Invalid testing mode: {}'.format(testing_mode))
    return ServiceClass(session_bus, object_path, loop)
