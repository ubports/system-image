# Copyright (C) 2013-2014 Canonical Ltd.
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
    'DISABLED',
    'config',
    ]


import os
import atexit

from configparser import ConfigParser
from contextlib import ExitStack
from pkg_resources import resource_filename
from systemimage.helpers import (
    Bag, as_loglevel, as_object, as_timedelta, makedirs, temporary_directory)


DISABLED = object()


def expand_path(path):
    return os.path.abspath(os.path.expanduser(path))


def port_value_converter(value):
    if value.lower() in ('disabled', 'disable'):
        return DISABLED
    result = int(value)
    if result < 0:
        raise ValueError(value)
    return result


def device_converter(value):
    return value.strip()


class Configuration:
    def __init__(self, ini_file=None):
        # Defaults.
        self.config_file = None
        self.service = Bag()
        self.system = Bag()
        if ini_file is None:
            ini_file = resource_filename('systemimage.data', 'client.ini')
        self.load(ini_file)
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
        self.service.update(converters=dict(http_port=port_value_converter,
                                            https_port=port_value_converter,
                                            build_number=int,
                                            device=device_converter,
                                            ),
                           **parser['service'])
        if (self.service.http_port is DISABLED and
            self.service.https_port is DISABLED):
            raise ValueError('Cannot disable both http and https ports')
        # Construct the HTTP and HTTPS base urls, which most applications will
        # actually use.  We do this in two steps, in order to support
        # disabling one or the other (but not both) protocols.
        if self.service.http_port == 80:
            http_base = 'http://{}'.format(self.service.base)
        elif self.service.http_port is DISABLED:
            http_base = None
        else:
            http_base = 'http://{}:{}'.format(
                self.service.base, self.service.http_port)
        # HTTPS.
        if self.service.https_port == 443:
            https_base = 'https://{}'.format(self.service.base)
        elif self.service.https_port is DISABLED:
            https_base = None
        else:
            https_base = 'https://{}:{}'.format(
                self.service.base, self.service.https_port)
        # Sanity check and final settings.
        if http_base is None:
            assert https_base is not None
            http_base = https_base
        if https_base is None:
            assert http_base is not None
            https_base = http_base
        self.service['http_base'] = http_base
        self.service['https_base'] = https_base
        try:
            self.system.update(converters=dict(timeout=as_timedelta,
                                               build_file=expand_path,
                                               loglevel=as_loglevel,
                                               settings_db=expand_path,
                                               tempdir=expand_path),
                              **parser['system'])
        except KeyError:
            # If we're overriding via a channel.ini file, it's okay if the
            # [system] section is missing.  However, the main configuration
            # ini file must include all sections.
            if not override:
                raise
        # Short-circuit, since we're loading a channel.ini file.
        self._override = override
        if override:
            return
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
        if self._device is None:
            # Start by looking for a [service]device setting.  Use this if it
            # exists, otherwise fall back to calling the hook.
            self._device = getattr(self.service, 'device', None)
            # The key could exist in the channel.ini file, but its value could
            # be empty.  That's semantically equivalent to a missing
            # [service]device setting.
            if not self._device:
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
