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

"""Update channels."""

__all__ = [
    'Channels',
    ]


import json

from resolver.helpers import Bag


class Channels(Bag):
    @classmethod
    def from_json(cls, data):
        mapping = json.loads(data)
        channels = {}
        # e.g. keys: daily, stable
        for channel_name, device_mapping in mapping.items():
            devices = {}
            # e.g. keys: nexus7, nexus4
            for device_name, detail_mapping in device_mapping.items():
                # Most of the keys at this level (e.g. index) have flat
                # values, however the keyring key is itself a mapping.
                keyring = detail_mapping.pop('keyring', None)
                if keyring is not None:
                    detail_mapping['keyring'] = Bag(**keyring)
                # e.g. nexus7 -> {index, keyring}
                devices[device_name] = Bag(**detail_mapping)
            # e.g. daily -> {nexus7, nexus4}
            channels[channel_name] = Bag(**devices)
        return cls(**channels)
