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

"""DBus service."""

__all__ = [
    'Service',
    'TestableService',
    ]


from dbus.service import Object, method
from systemimage.api import Mediator


class Service(Object):
    """Main dbus service."""

    def __init__(self, bus, object_path):
        super().__init__(bus, object_path)
        self._api = Mediator()

    @property
    def api(self):
        return self._api

    @method('com.canonical.SystemImage', out_signature='i')
    def BuildNumber(self):
        return self.api.get_build_number()

    @method('com.canonical.SystemImage', out_signature='b')
    def IsUpdateAvailable(self):
        return bool(self.api.check_for_update())

    @method('com.canonical.SystemImage', out_signature='x')
    def GetUpdateSize(self):
        return self.api.check_for_update().size

    @method('com.canonical.SystemImage', out_signature='i')
    def GetUpdateVersion(self):
        return self.api.check_for_update().version

    @method('com.canonical.SystemImage', out_signature='aa{ss}')
    def GetDescriptions(self):
        return self.api.check_for_update().descriptions


class TestableService(Service):
    """For testing purposes only."""

    @property
    def api(self):
        # Reset the api object so that the tests have isolated state.
        current_api = self._api
        self._api = Mediator()
        return current_api
