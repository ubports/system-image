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

"""Test helpers."""

__all__ = [
    'get_channels',
    'get_index',
    'make_index',
    ]


from pkg_resources import resource_string as resource_bytes
from resolver.channel import Channels
from resolver.index import Index
from textwrap import dedent


def get_index(filename):
    json_bytes = resource_bytes('resolver.tests.data', filename)
    return make_index(json_bytes.decode('utf-8'))


def make_index(json_string):
    return Index.from_json(dedent(json_string))


def get_channels(filename):
    json_bytes = resource_bytes('resolver.tests.data', filename)
    return Channels.from_json(json_bytes.decode('utf-8'))
