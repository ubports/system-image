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

"""Device type calculation."""

__all__ = [
    'SystemProperty',
    ]


import logging

from subprocess import CalledProcessError, check_output


class BaseDevice:
    """Common device calculation actions."""

    def get_device(self): # pragma: no cover
        """Subclasses must override this."""
        raise NotImplementedError


class SystemProperty(BaseDevice):
    """Get the device type through system properties."""

    def get_device(self):
        log = logging.getLogger('systemimage')
        try:
            stdout = check_output(
                'getprop ro.product.device'.split(), universal_newlines=True)
        except:
            pass
        if stdout and stdout == '':
            # Try to use device-info instead
            try:
                stdout = check_output(
                    'device-info get Name'.split(), universal_newlines=True)
            except:
                log.exception('Could not determine device name from either getprop or device-info!')
                return '?'
        return stdout.strip()
