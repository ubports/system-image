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
import atexit

from configparser import ConfigParser
from contextlib import ExitStack
from pkg_resources import resource_filename
from systemimage.helpers import (
    Bag, as_loglevel, as_object, as_timedelta, makedirs, temporary_directory)


def expand_path(path):
    return os.path.abspath(os.path.expanduser(path))


class Configuration:
    def __init__(self):
        # Defaults.
        self.config_file = None
        ini_path = resource_filename('systemimage.data', 'client.ini')
        self.load(ini_path)
        self._override = False
        # 2013-10-14 BAW This is a placeholder for rendezvous between the
        # downloader and the D-Bus service.  When running udner D-Bus and we
        # get a `paused` signal from the download manager, we need this to
        # plumb through an UpdatePaused signal to our clients.  It rather
        # sucks that we need a global for this, but I can't get the plumbing
        # to work otherwise.  This seems like the least horrible place to
        # stash this global.
        self.dbus_service = None
        # Cache/overrides.
        self._device = None
        self._build_number = None
        self._channel = None
        self._tempdir = None
        self._resources = ExitStack()
        atexit.register(self._resources.close)

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
                return self.service.build_number
            else:
                try:
                    with open(self.system.build_file, encoding='utf-8') as fp:
                        return int(fp.read().strip())
                except FileNotFoundError:
                    return 0
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
    def build_number_cli(self):
        return self._build_number

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

    @property
    def tempdir(self):
        if self._tempdir is None:
            makedirs(self.system.tempdir)
            self._tempdir = self._resources.enter_context(
                temporary_directory(prefix='system-image-',
                                    dir=self.system.tempdir))
        return self._tempdir


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
