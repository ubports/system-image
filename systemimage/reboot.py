# Copyright (C) 2013-2014 Canonical Ltd.
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
    'BaseReboot',
    'Reboot',
    'factory_reset',
    ]


import os
import logging

from subprocess import CalledProcessError, check_call
from systemimage.config import config
from systemimage.helpers import atomic

log = logging.getLogger('systemimage')


class BaseReboot:
    """Common reboot actions."""

    def reboot(self):
        """Subclasses must override this."""
        raise NotImplementedError


class Reboot(BaseReboot):
    """Issue a standard reboot."""

    def reboot(self):
        try:
            check_call('/sbin/reboot -f recovery'.split(),
                       universal_newlines=True)
        except CalledProcessError as error:
            log.exception('reboot exit status: {}'.format(error.returncode))
            raise


def factory_reset():
    """Perform a factory reset."""
    command_file = os.path.join(
        config.updater.cache_partition, 'ubuntu_command')
    with atomic(command_file) as fp:
        print('format data', file=fp)
    log.info('Performing a factory reset')
    config.hooks.reboot().reboot()
