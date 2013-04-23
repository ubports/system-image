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

"""Device/channel indexes."""

__all__ = [
    'Index',
    ]


import json

from datetime import datetime, timezone
from resolver.helpers import Bag

FMT = '%a %b %d %H:%M:%S %Z %Y'


class Index(Bag):
    @classmethod
    def from_json(cls, data):
        mapping = json.loads(data)
        # Parse the bundles.
        bundles = []
        for bundle_data in mapping['bundles']:
            images = Bag(**bundle_data['images'])
            bundle = Bag(images=images, version=bundle_data['version'])
            bundles.append(bundle)
        # Parse the global data, of which there is only the timestamp.  Even
        # though the string will contain 'UTC' (which we assert is so since we
        # can only handle UTC timestamps), strptime() will return a naive
        # datetime.  We'll turn it into an aware datetime in UTC, which is the
        # only thing that can possibly make sense.
        timestamp_str = mapping['global']['generated_at']
        assert 'UTC' in timestamp_str.split(), 'timestamps must be UTC'
        naive_generated_at = datetime.strptime(timestamp_str, FMT)
        generated_at=naive_generated_at.replace(tzinfo=timezone.utc)
        global_ = Bag(generated_at=generated_at)
        # Parse the images.
        images = []
        for image_data in mapping['images']:
            image = Bag(**image_data)
            images.append(image)
        return cls(bundles=bundles, global_=global_, images=images)
