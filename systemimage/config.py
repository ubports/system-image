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

"""Read the configuration file."""

__all__ = [
    'Configuration',
    'config',
    ]


import os
import atexit

from configparser import ConfigParser
from contextlib import ExitStack
from pathlib import Path
from systemimage.bag import Bag
from systemimage.deviceStats import DeviceStats
from systemimage.helpers import (
    NO_PORT, as_loglevel, as_object, as_port, as_stripped, as_timedelta,
    makedirs, temporary_directory)

SECTIONS = ('service', 'system', 'gpg', 'updater', 'hooks', 'dbus')
USER_AGENT = ('Ubuntu System Image Upgrade Client: '
              'device={0.device};channel={0.channel};build={0.build_number};'
              'session={0.session};instance={0.instance}')


def expand_path(path):
    return os.path.abspath(os.path.expanduser(path))


class SafeConfigParser(ConfigParser):
    """Like ConfigParser, but with default empty sections.

    This makes the **style of loading keys/values into the Bag objects a
    little cleaner since it doesn't have to worry about KeyErrors when a
    configuration file doesn't contain a section, which is allowed.
    """

    def __init__(self, *args, **kws):
        super().__init__(args, **kws)
        for section in SECTIONS:
            self[section] = {}


class Configuration:
    def __init__(self, directory=None):
        self._set_defaults()
        # Because the configuration object is a global singleton, it makes for
        # a convenient place to stash information used by widely separate
        # components.  For example, this is a placeholder for rendezvous
        # between the downloader and the D-Bus service.  When running under
        # D-Bus and we get a `paused` signal from the download manager, we need
        # this to plumb through an UpdatePaused signal to our clients.  It
        # rather sucks that we need a global for this, but I can't get the
        # plumbing to work otherwise.  This seems like the least horrible place
        # to stash this global.
        self.dbus_service = None
        # These are used to plumb command line arguments from the main() to
        # other parts of the system.
        self.skip_gpg_verification = False
        self.override_gsm = False
        # Cache.
        self._device = None
        self._build_number = None
        self.build_number_override = False
        self._channel = None
        # This is used only to override the phased percentage via command line
        # and the property setter.
        self._phase_override = None
        self._tempdir = None
        self.config_d = None
        self.ini_files = []
        self.http_base = None
        self.https_base = None
        if directory is not None:
            self.load(directory)
        self._calculate_http_bases()
        self._resources = ExitStack()
        self._stats = DeviceStats()
        atexit.register(self._resources.close)

    def _set_defaults(self):
        self.service = Bag(
            base='system-image.ubports.com',
            http_port=80,
            https_port=443,
            channel='daily',
            build_number=0,
            )
        self.system = Bag(
            timeout=as_timedelta('1h'),
            tempdir='/tmp',
            logfile='/var/log/system-image/client.log',
            loglevel=as_loglevel('info'),
            settings_db='/var/lib/system-image/settings.db',
            )
        self.gpg = Bag(
            archive_master='/usr/share/system-image/archive-master.tar.xz',
            image_master='/var/lib/system-image/keyrings/image-master.tar.xz',
            image_signing=
                '/var/lib/system-image/keyrings/image-signing.tar.xz',
            device_signing=
                '/var/lib/system-image/keyrings/device-signing.tar.xz',
            )
        self.updater = Bag(
            cache_partition='/android/cache/recovery',
            data_partition='/var/lib/system-image',
            )
        self.hooks = Bag(
            device=as_object('systemimage.device.SystemProperty'),
            scorer=as_object('systemimage.scores.WeightedScorer'),
            apply=as_object('systemimage.apply.Reboot'),
            )
        self.dbus = Bag(
            lifetime=as_timedelta('10m'),
            )

    def _load_file(self, path):
        parser = SafeConfigParser()
        str_path = str(path)
        parser.read(str_path)
        self.ini_files.append(path)
        self.service.update(converters=dict(http_port=as_port,
                                            https_port=as_port,
                                            build_number=int,
                                            device=as_stripped,
                                            ),
                            **parser['service'])
        self.system.update(converters=dict(timeout=as_timedelta,
                                           loglevel=as_loglevel,
                                           settings_db=expand_path,
                                           tempdir=expand_path),
                            **parser['system'])
        self.gpg.update(**parser['gpg'])
        self.updater.update(**parser['updater'])
        self.hooks.update(converters=dict(device=as_object,
                                          scorer=as_object,
                                          apply=as_object),
                          **parser['hooks'])
        self.dbus.update(converters=dict(lifetime=as_timedelta),
                         **parser['dbus'])

    def load(self, directory):
        """Load up the configuration from a config.d directory."""
        # Look for all the files in the given directory with .ini or .cfg
        # suffixes.  The files must start with a number, and the files are
        # loaded in numeric order.
        if self.config_d is not None:
            raise RuntimeError('Configuration already loaded; use .reload()')
        self.config_d = directory
        if not Path(directory).is_dir():
            raise TypeError(
                '.load() requires a directory: {}'.format(directory))
        candidates = []
        for child in Path(directory).glob('*.ini'):
            order, _, base = child.stem.partition('_')
            # XXX 2014-10-03: The logging system isn't initialized when we get
            # here, so we can't log that these files are being ignored.
            if len(_) == 0:
                continue
            try:
                serial = int(order)
            except ValueError:
                continue
            candidates.append((serial, child))
        for serial, path in sorted(candidates):
            self._load_file(path)
        self._calculate_http_bases()

    def reload(self):
        """Reload the configuration directory."""
        # Reset some cached attributes.
        directory = self.config_d
        self.ini_files = []
        self.config_d = None
        self._build_number = None
        # Now load the defaults, then reload the previous config.d directory.
        self._set_defaults()
        self.load(directory)

    def _calculate_http_bases(self):
        if (self.service.http_port is NO_PORT and
            self.service.https_port is NO_PORT):
            raise ValueError('Cannot disable both http and https ports')
        # Construct the HTTP and HTTPS base urls, which most applications will
        # actually use.  We do this in two steps, in order to support disabling
        # one or the other (but not both) protocols.
        if self.service.http_port == 80:
            http_base = 'http://{}'.format(self.service.base)
        elif self.service.http_port is NO_PORT:
            http_base = None
        else:
            http_base = 'http://{}:{}'.format(
                self.service.base, self.service.http_port)
        # HTTPS.
        if self.service.https_port == 443:
            https_base = 'https://{}'.format(self.service.base)
        elif self.service.https_port is NO_PORT:
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
        self.http_base = http_base
        self.https_base = https_base

    @property
    def build_number(self):
        if self._build_number is None:
            self._build_number = self.service.build_number
        return self._build_number

    @build_number.setter
    def build_number(self, value):
        if not isinstance(value, int):
            raise ValueError(
                'integer is required, got: {}'.format(type(value).__name__))
        self._build_number = value
        self.build_number_override = True

    @build_number.deleter
    def build_number(self):
        self._build_number = None

    @property
    def device(self):
        if self._device is None:
            # Start by looking for a [service]device setting.  Use this if it
            # exists, otherwise fall back to calling the hook.
            self._device = getattr(self.service, 'device', None)
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
    def phase_override(self):
        return self._phase_override

    @phase_override.setter
    def phase_override(self, value):
        self._phase_override = max(0, min(100, int(value)))

    @phase_override.deleter
    def phase_override(self):
        self._phase_override = None

    @property
    def tempdir(self):
        if self._tempdir is None:
            makedirs(self.system.tempdir)
            self._tempdir = self._resources.enter_context(
                temporary_directory(prefix='system-image-',
                                    dir=self.system.tempdir))
        return self._tempdir

    @property
    def session(self):
        return self._stats.getSessionId()

    @property
    def instance(self):
        return self._stats.getInstanceId()

    @property
    def user_agent(self):
        return USER_AGENT.format(self)


# Define the global configuration object.  We use a proxy here so that
# post-object creation loading will work.

_config = Configuration()

class _Proxy:
    def __getattribute__(self, name):
        return getattr(_config, name)
    def __setattr__(self, name, value):
        setattr(_config, name, value)
    def __delattr__(self, name):
        delattr(_config, name)


config = _Proxy()
