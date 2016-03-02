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

"""Update channels."""

__all__ = [
    'Channels',
    ]


import json

from systemimage.bag import Bag


def _parse_device_mappings(device_mapping):
    devices = {}
    # e.g. keys: nexus7, nexus4
    for device_name, mapping_1 in device_mapping.items():
        # Most of the keys at this level (e.g. index) have flat values,
        # however the keyring key is itself a mapping.
        keyring = mapping_1.pop('keyring', None)
        if keyring is not None:
            mapping_1['keyring'] = Bag(**keyring)
        # e.g. nexus7 -> {index, keyring}
        devices[device_name] = Bag(**mapping_1)
    return Bag(**devices)


class Channels(Bag):
    @classmethod
    def from_json(cls, data):
        mapping = json.loads(data)
        channels = {}
        for channel_name, mapping_1 in mapping.items():
            hidden = mapping_1.pop('hidden', None)
            if hidden is None:
                hidden = False
            else:
                assert hidden in (True, False), (
                    "Unexpected value for 'hidden': {}".format(hidden))
            mapping_1['hidden'] = hidden
            device_mapping = mapping_1.pop('devices')
            mapping_1['devices'] = _parse_device_mappings(device_mapping)
            channels[channel_name] = Bag(**mapping_1)
        return cls(**channels)
