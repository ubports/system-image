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


def expand_path(path):
    return os.path.abspath(os.path.expanduser(path))


class Configuration:
    def __init__(self):
        # Defaults.
        defaults_ini = resource_filename('resolver.data', 'defaults.ini')
        self.load(defaults_ini)

    def load(self, path):
        parser = ConfigParser()
        parser.read(path)
        self.service = Bag(converters=dict(timeout=as_timedelta,
                                           threads=int,
                                           http_port=int,
                                           https_port=int),
                           **parser['service'])
        # Construct the HTTP and HTTPS base urls, which most applications will
        # actually use.
        if self.service.http_port == 80:
            self.service['http_base'] = 'http://{}'.format(self.service.base)
        else:
            self.service['http_base'] = 'http://{}:{}'.format(
                self.service.base, self.service.http_port)
        if self.service.https_port == 443:
            self.service['https_base'] = 'https://{}'.format(self.service.base)
        else:
            self.service['https_base'] = 'https://{}:{}'.format(
                self.service.base, self.service.https_port)
        self.system = Bag(converters=dict(build_file=expand_path,
                                          tempdir=expand_path),
                          **parser['system'])

    def get_build_number(self):
        try:
            with open(self.system.build_file, encoding='utf-8') as fp:
                return int(fp.read().strip())
        except FileNotFoundError:
            return 0


# Define the global configuration object.  Normal use can be as simple as:
#
# from resolver.config import config
# build_file = config.system.build_file
#
# In the test suite though, the actual configuration object can be easily
# patched by doing something like this:
#
# test_config = Configuration(...)
# with unittest.mock.patch('config._config', test_config):
#     run_test()
#
# and now every module which does the first code example will get build_file
# from the mocked Configuration instance.

_config = Configuration()

class _Proxy:
    def __getattribute__(self, name):
        return getattr(_config, name)

config = _Proxy()
