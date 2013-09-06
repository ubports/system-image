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

from systemimage.helpers import Bag


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
        # LP: #1221841 introduced a new channels.json format which introduced
        # a new level between the channel name and the device name.  This
        # extra level can include optional 'alias' and 'hidden' keys, and must
        # include a 'devices' key.  Until LP: #1221843 we must support both
        # formats, so to figure out which we're looking at, see if there's a
        # 'devices' key under the channel name.  We'll just assume there won't
        # be a device called 'device'.
        for channel_name, mapping_1 in mapping.items():
            if 'devices' in mapping_1:
                # New style.
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
            else:
                # For better forward compatibility, even old style
                # channel.json files get a 'devices' level.
                device_mapping = _parse_device_mappings(mapping_1)
                channels[channel_name] = Bag(devices=device_mapping)
        return cls(**channels)
