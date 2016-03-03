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

"""Reboot issuer."""

__all__ = [
    'BaseApply',
    'Noop',
    'Reboot',
    'factory_reset',
    'production_reset',
    ]


import os
import logging

from subprocess import CalledProcessError, check_call
from systemimage.config import config
from systemimage.helpers import atomic

log = logging.getLogger('systemimage')


class BaseApply:
    """Common apply-the-update actions."""

    def apply(self): # pragma: no cover
        """Subclasses must override this."""
        raise NotImplementedError


class Reboot(BaseApply):
    """Apply the update by rebooting the device."""

    def apply(self):
        try:
            check_call('/sbin/reboot -f recovery'.split(),
                       universal_newlines=True)
        except CalledProcessError as error:
            log.exception('reboot exit status: {}'.format(error.returncode))
            raise
        # This code may or may not run.  We're racing against the system
        # reboot procedure.
        config.dbus_service.Rebooting(True)


class Noop(BaseApply):
    """No-op apply, mostly for testing."""

    def apply(self):
        pass


def factory_reset():
    """Perform a factory reset."""
    command_file = os.path.join(
        config.updater.cache_partition, 'ubuntu_command')
    with atomic(command_file) as fp:
        print('format data', file=fp)
    log.info('Performing a factory reset')
    config.hooks.apply().apply()


def production_reset():
    """Perform a production reset."""
    command_file = os.path.join(
        config.updater.cache_partition, 'ubuntu_command')
    with atomic(command_file) as fp:
        print('format data', file=fp)
        print('enable factory_wipe', file=fp)
    log.info('Performing a production factory reset')
    config.hooks.apply().apply()
