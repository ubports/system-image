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

"""Nodes in the JSON resource tree."""

__all__ = [
    'Channel',
    'Channels',
    'Index',
    ]


import json

from datetime import datetime, timezone


FMT = '%a %b %d %H:%M:%S %Z %Y'


class Index:
    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.bundles = {}
        self.images = []
        self.generated_at = None

    def extend(self, data):
        mapping = json.loads(data)
        # Parse the timestamp.  Even though the string will contain 'UTC'
        # (which we assert is so since we can only handle UTC timestamps),
        # strptime() will return a naive datetime.  We'll turn it into an
        # aware datetime in UTC, which is the only thing that can possibly
        # make sense.
        timestamp_str = mapping['global']['generated_at']
        assert 'UTC' in timestamp_str.split(), 'timestamps must be UTC'
        generated_at = datetime.strptime(timestamp_str, FMT)
        self.generated_at = generated_at.replace(tzinfo=timezone.utc)
        # Fill out the bundles.
        ## for bundle_name, bundle_data in mapping['bundles'].items():
        ##     pass


class Channel:
    def __init__(self, name, indexes):
        self.name = name
        self.indexes = indexes


class Channels:
    def __init__(self, data):
        self.channels = {}
        mapping = json.loads(data)
        for channel_name, index_data in mapping.items():
            indexes = {}
            for index_name, path in index_data.items():
                index = Index(index_name, path)
                indexes[index_name] = index
            channel = Channel(channel_name, indexes)
            self.channels[channel_name] = channel
