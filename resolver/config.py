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

"""Read the configuration file."""

__all__ = [
    'Configuration',
    'config',
    ]


import os

# BAW 2013-04-23: If we need something more sophisticated, lazr.config is the
# way to go.  It provides a nice testing infrastruction (pushing/popping of
# configurations), schema definition, and a slew of useful data type
# conversion functions.  For now, we limit the non-stdlib dependencies and
# roll our own.
from configparser import ConfigParser
from pkg_resources import resource_filename
from resolver.helpers import Bag, as_timedelta


class Configuration:
    def __init__(self):
        # Defaults.
        defaults_ini = resource_filename('resolver.data', 'defaults.ini')
        self.load(defaults_ini)

    def load(self, path):
        parser = ConfigParser()
        parser.read(path)
        self.service = Bag(
            base=parser['service']['base'],
            threads=int(parser['service']['threads']),
            timeout=as_timedelta(parser['service']['timeout']),
            )
        self.cache = Bag(
            directory=os.path.expanduser(parser['cache']['directory']),
            lifetime=as_timedelta(parser['cache']['lifetime']),
            )
        self.upgrade = Bag(
            channel=parser['upgrade']['channel'],
            device=parser['upgrade']['device'],
            )


# This is the global configuration object.  It uses the defaults, but the
# argument parsing can call load() on it to initialize it with a new .ini
# file.
config = Configuration()
