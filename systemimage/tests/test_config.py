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

"""Test the configuration parser."""

__all__ = [
    'TestConfiguration',
    ]


import os
import sys
import stat
import shutil
import logging
import unittest

from contextlib import ExitStack, contextmanager
from datetime import timedelta
from subprocess import CalledProcessError, check_output
from systemimage.config import Configuration
from systemimage.device import SystemProperty
from systemimage.reboot import Reboot
from systemimage.scores import WeightedScorer
from systemimage.testing.helpers import configuration, data_path, touch_build
from unittest.mock import patch


@contextmanager
def _patch_device_hook():
    # The device hook has two things that generally need patching.  The first
    # is the logging output, which is just noise for testing purposes, so
    # silence it.  The second is that the `getprop` command may actually exist
    # on test system, and we want a consistent environment (i.e. the
    # assumption that the command does not exist).
    with ExitStack() as resources:
        resources.enter_context(patch('systemimage.device.logging.getLogger'))
        resources.enter_context(
            patch('systemimage.device.check_output',
                  side_effect=FileNotFoundError))
        yield


class TestConfiguration(unittest.TestCase):
    def test_defaults(self):
        config = Configuration()
        # [service]
        self.assertEqual(config.service.base, 'system-image.ubuntu.com')
        self.assertEqual(config.http_base, 'http://system-image.ubuntu.com')
        self.assertEqual(config.https_base, 'https://system-image.ubuntu.com')
        self.assertEqual(config.service.channel, 'daily')
        self.assertEqual(config.service.build_number, 0)
        # [system]
        self.assertEqual(config.system.tempdir, '/tmp')
        self.assertEqual(config.system.logfile,
                         '/var/log/system-image/client.log')
        self.assertEqual(config.system.loglevel,
                         (logging.INFO, logging.ERROR))
        self.assertEqual(config.system.settings_db,
                         '/var/lib/system-image/settings.db')
        # [hooks]
        self.assertEqual(config.hooks.device, SystemProperty)
        self.assertEqual(config.hooks.scorer, WeightedScorer)
        self.assertEqual(config.hooks.reboot, Reboot)
        # [gpg]
        self.assertEqual(config.gpg.archive_master,
                         '/etc/system-image/archive-master.tar.xz')
        self.assertEqual(
            config.gpg.image_master,
            '/var/lib/system-image/keyrings/image-master.tar.xz')
        self.assertEqual(
            config.gpg.image_signing,
            '/var/lib/system-image/keyrings/image-signing.tar.xz')
        self.assertEqual(
            config.gpg.device_signing,
            '/var/lib/system-image/keyrings/device-signing.tar.xz')
        # [updater]
        self.assertEqual(config.updater.cache_partition,
                         '/android/cache/recovery')
        self.assertEqual(config.updater.data_partition,
                         '/var/lib/system-image')
        # [dbus]
        self.assertEqual(config.dbus.lifetime.total_seconds(), 600)

    @configuration('config_01.ini')
    def test_basic_config_d(self, config):
        # Read a basic config.d directory and check that the various attributes
        # and values are correct.
        #
        # [service]
        self.assertEqual(config.service.base, 'phablet.example.com')
        self.assertEqual(config.http_base, 'http://phablet.example.com')
        self.assertEqual(config.https_base, 'https://phablet.example.com')
        self.assertEqual(config.service.channel, 'stable')
        self.assertEqual(config.service.build_number, 0)
        # [system]
        self.assertEqual(config.system.tempdir, '/tmp')
        self.assertEqual(config.system.logfile,
                         '/var/log/system-image/client.log')
        self.assertEqual(config.system.loglevel,
                         (logging.ERROR, logging.ERROR))
        self.assertEqual(config.system.settings_db,
                         '/var/lib/phablet/settings.db')
        self.assertEqual(config.system.timeout, timedelta(seconds=10))
        # [hooks]
        self.assertEqual(config.hooks.device, SystemProperty)
        self.assertEqual(config.hooks.scorer, WeightedScorer)
        self.assertEqual(config.hooks.reboot, Reboot)
        # [gpg]
        self.assertEqual(config.gpg.archive_master,
                         '/etc/phablet/archive-master.tar.xz')
        self.assertEqual(config.gpg.image_master,
                         '/etc/phablet/image-master.tar.xz')
        self.assertEqual(config.gpg.image_signing,
                         '/var/lib/phablet/image-signing.tar.xz')
        self.assertEqual(config.gpg.device_signing,
                         '/var/lib/phablet/device-signing.tar.xz')
        # [updater]
        self.assertEqual(config.updater.cache_partition[-14:],
                         '/android/cache')
        self.assertEqual(config.updater.data_partition[-20:],
                         '/lib/phablet/updater')
        # [dbus]
        self.assertEqual(config.dbus.lifetime.total_seconds(), 120)

    @configuration('config_10.ini')
    def test_special_dbus_logging_level(self, config):
        # Read a config.ini that has a loglevel value with an explicit dbus
        # logging level.
        self.assertEqual(config.system.loglevel,
                         (logging.CRITICAL, logging.DEBUG))

    @configuration('config_02.ini')
    def test_nonstandard_ports(self, config):
        # config_02.ini has non-standard http and https ports.
        self.assertEqual(config.service.base, 'phablet.example.com')
        self.assertEqual(config.http_base, 'http://phablet.example.com:8080')
        self.assertEqual(config.https_base,
                         'https://phablet.example.com:80443')

    @configuration('config_05.ini')
    def test_disabled_http_port(self, config):
        # config_05.ini has http port disabled and non-standard https port.
        self.assertEqual(config.service.base, 'phablet.example.com')
        self.assertEqual(config.http_base, 'https://phablet.example.com:80443')
        self.assertEqual(config.https_base,
                         'https://phablet.example.com:80443')

    @configuration('config_06.ini')
    def test_disabled_https_port(self, config):
        # config_06.ini has https port disabled and standard http port.
        self.assertEqual(config.service.base, 'phablet.example.com')
        self.assertEqual(config.http_base, 'http://phablet.example.com')
        self.assertEqual(config.https_base, 'http://phablet.example.com')

    @configuration
    def test_both_ports_disabled(self, config_d):
        # config_07.ini has both http and https ports disabled.
        shutil.copy(data_path('config_07.ini'),
                    os.path.join(config_d, '01_override.ini'))
        config = Configuration()
        with self.assertRaises(ValueError) as cm:
            config.load(config_d)
        self.assertEqual(cm.exception.args[0],
                         'Cannot disable both http and https ports')

    @configuration
    def test_negative_port_number(self, config_d):
        # config_08.ini has a negative port number.
        shutil.copy(data_path('config_08.ini'),
                    os.path.join(config_d, '01_override.ini'))
        with self.assertRaises(ValueError) as cm:
            Configuration(config_d)
        self.assertEqual(cm.exception.args[0], '-1')

    @configuration
    def test_get_build_number(self, config):
        # The current build number is stored in a file specified in the
        # configuration file.
        touch_build(1500)
        config.reload()
        self.assertEqual(config.build_number, 1500)

    @configuration
    def test_get_build_number_after_reload(self, config):
        # After a reload, the build number gets updated.
        self.assertEqual(config.build_number, 0)
        touch_build(801)
        config.reload()
        self.assertEqual(config.build_number, 801)

    @configuration
    def test_get_build_number_missing(self, config):
        # The build file is missing, so the build number defaults to 0.
        self.assertEqual(config.build_number, 0)

    @configuration
    def test_get_device_name(self, config):
        # The device name as we'd expect it to work on a real image.
        with patch('systemimage.device.check_output', return_value='nexus7'):
            self.assertEqual(config.device, 'nexus7')
            # Get it again to test out the cache.
            self.assertEqual(config.device, 'nexus7')

    @configuration
    def test_get_device_name_fallback(self, config):
        # Fallback for testing on non-images.
        # Silence the log exceptions this will provoke.
        with patch('systemimage.device.logging.getLogger'):
            # It's possible getprop actually does exist on the system.
            with patch('systemimage.device.check_output',
                       side_effect=CalledProcessError(1, 'ignore')):
                self.assertEqual(config.device, '?')

    @configuration
    def test_device_no_getprop_fallback(self, config):
        # Like above, but a FileNotFoundError occurs instead.
        with _patch_device_hook():
            self.assertEqual(config.device, '?')

    @configuration
    def test_get_channel(self, config):
        self.assertEqual(config.channel, 'stable')

    @configuration
    def test_overrides(self, config):
        self.assertEqual(config.build_number, 0)
        self.assertEqual(config.device, 'nexus7')
        self.assertEqual(config.channel, 'stable')
        config.build_number = 20250801
        config.device = 'phablet'
        config.channel = 'daily-proposed'
        self.assertEqual(config.build_number, 20250801)
        self.assertEqual(config.device, 'phablet')
        self.assertEqual(config.channel, 'daily-proposed')

    @configuration
    def test_bad_override(self, config):
        with self.assertRaises(ValueError) as cm:
            # Looks like an int, but isn't.
            config.build_number = '20150801'
        self.assertEqual(str(cm.exception), 'integer is required, got: str')

    @configuration
    def test_reset_build_number(self, config):
        old_build = config.build_number
        self.assertEqual(old_build, 0)
        config.build_number = 20990000
        self.assertEqual(config.build_number, 20990000)
        del config.build_number
        self.assertEqual(config.build_number, 0)
        config.build_number = 21000000
        self.assertEqual(config.build_number, 21000000)

    @configuration('00.ini', 'config_11.ini')
    def test_later_files_override(self, config):
        # This value comes from the 00.ini file.
        self.assertEqual(config.system.timeout, timedelta(seconds=1))
        # These get overridden in config_11.ini.
        self.assertEqual(config.service.base, 'systum-imaje.ubuntu.com')
        self.assertEqual(config.dbus.lifetime, timedelta(hours=1))

    @configuration
    def test_tempdir(self, config):
        # config.tempdir is randomly created.
        self.assertEqual(config.tempdir[-26:-8], '/tmp/system-image-')
        self.assertEqual(stat.filemode(os.stat(config.tempdir).st_mode),
                         'drwx--S---')

    def test_tempdir_cleanup(self):
        # config.tempdir gets cleaned up when the process exits gracefully.
        #
        # To test this, we invoke Python in a subprocess and ask it to print
        # config.tempdir, letting that process exit normally.  Then check that
        # the directory has been removed.  Note of course that *ungraceful*
        # exits won't invoke the atexit handlers and thus won't clean up the
        # directory.  Be sure [system]tempdir is on a tempfs and you'll be
        # fine.
        command = [
            sys.executable,
            '-c',
            """from systemimage.config import config; import stat, os; \
               print(stat.filemode(os.stat(config.tempdir).st_mode), \
               config.tempdir)"""
            ]
        stdout = check_output(command, universal_newlines=True)
        self.assertEqual(stdout[:29], 'drwx--S--- /tmp/system-image-')
        self.assertFalse(os.path.exists(stdout.split()[1]))

    @configuration('config_09.ini')
    def test_missing_stanza_okay(self, config):
        # config_09.ini does not contain a [system] section, so that gets set
        # to the built-in default values.
        self.assertEqual(config.system.logfile,
                         '/var/log/system-image/client.log')
