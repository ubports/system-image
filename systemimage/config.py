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
from systemimage.helpers import Bag, as_object, as_timedelta, as_loglevel


def expand_path(path):
    return os.path.abspath(os.path.expanduser(path))


class Configuration:
    def __init__(self):
        # Defaults.
        self.config_file = None
        ini_path = resource_filename('systemimage.data', 'client.ini')
        self.load(ini_path)
        self._override = False
        # Cache/overrides.
        self._device = None
        self._build_number = None
        self._channel = None

    def load(self, path, *, override=False):
        parser = ConfigParser()
        files_read = parser.read(path)
        if files_read != [path]:
            raise FileNotFoundError(path)
        self.config_file = path
        self.service = Bag(converters=dict(http_port=int,
                                           https_port=int,
                                           build_number=int),
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
        # Short-circuit, since we're loading a channel.ini file.
        self._override = override
        if override:
            return
        self.system = Bag(converters=dict(timeout=as_timedelta,
                                          threads=int,
                                          build_file=expand_path,
                                          loglevel=as_loglevel,
                                          settings_db=expand_path,
                                          state_file=expand_path,
                                          tempdir=expand_path),
                          **parser['system'])
        self.gpg = Bag(**parser['gpg'])
        self.updater = Bag(**parser['updater'])
        self.hooks = Bag(converters=dict(device=as_object,
                                         scorer=as_object,
                                         reboot=as_object),
                         **parser['hooks'])
        self.dbus = Bag(converters=dict(lifetime=as_timedelta),
                        **parser['dbus'])

    @property
    def build_number(self):
        if self._build_number is None:
            if self._override:
                self._build_number = self.service.build_number
            else:
                try:
                    with open(self.system.build_file, encoding='utf-8') as fp:
                        self._build_number = int(fp.read().strip())
                except FileNotFoundError:
                    self._build_number = 0
        return self._build_number

    @build_number.setter
    def build_number(self, value):
        if not isinstance(value, int):
            raise ValueError(
                'integer is required, got: {}'.format(type(value).__name__))
        self._build_number = value

    @build_number.deleter
    def build_number(self):
        self._build_number = None

    @property
    def device(self):
        # It's safe to cache this.
        if self._device is None:
            self._device = self.hooks.device().get_device()
        return self._device

    @device.setter
    def device(self, value):
        self._device = value

    @property
    def channel(self):
        if self._channel is None:
            self._channel = self.service.channel
        return self._channel

    @channel.setter
    def channel(self, value):
        self._channel = value


# Define the global configuration object.  Normal use can be as simple as:
#
# from systemimage.config import config
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
    def __setattr__(self, name, value):
        setattr(_config, name, value)
    def __delattr__(self, name):
        delattr(_config, name)


config = _Proxy()
