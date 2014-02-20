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
    ]


import logging

from subprocess import CalledProcessError, check_call


class BaseReboot:
    """Common reboot actions."""

    def reboot(self):
        """Subclasses must override this."""
        raise NotImplementedError


class Reboot(BaseReboot):
    """Issue a standard reboot."""

    def reboot(self):
        log = logging.getLogger('systemimage')
        try:
            check_call('/sbin/reboot -f recovery'.split(),
                       universal_newlines=True)
        except CalledProcessError as error:
            log.exception('reboot exit status: {}'.format(error.returncode))
            raise
