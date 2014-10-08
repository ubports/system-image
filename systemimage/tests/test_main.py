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

"""Test the main entry point."""

__all__ = [
    'TestCLIDuplicateDestinations',
    'TestCLIFilters',
    'TestCLIListChannels',
    'TestCLIMain',
    'TestCLIMainDryRun',
    'TestCLIMainDryRunAliases',
    'TestCLINoReboot',
    'TestCLISettings',
    'TestCLIFactoryReset',
    'TestDBusMain',
    ]


import os
import sys
import dbus
import stat
import time
import shutil
import unittest
import subprocess

from contextlib import ExitStack, contextmanager
from datetime import datetime
from functools import partial
from io import StringIO
from pathlib import Path
from pkg_resources import resource_filename, resource_string as resource_bytes
from systemimage.config import Configuration, config
from systemimage.helpers import safe_remove
from systemimage.main import main as cli_main
from systemimage.settings import Settings
from systemimage.testing.helpers import (
    ServerTestBase, chmod, configuration, copy, data_path, find_dbus_process,
    temporary_directory, touch_build)
from systemimage.testing.nose import SystemImagePlugin
from textwrap import dedent
from unittest.mock import MagicMock, patch


SPACE = ' '
TIMESTAMP = datetime(2013, 8, 1, 12, 11, 10).timestamp()


@contextmanager
def umask(new_mask):
    old_mask = None
    try:
        old_mask = os.umask(new_mask)
        yield
    finally:
        if old_mask is not None:
            os.umask(old_mask)


class TestCLIMain(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        try:
            self._stdout = StringIO()
            self._stderr = StringIO()
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            self._resources.enter_context(
                patch('builtins.print', partial(print, file=self._stdout)))
            # Patch argparse's stderr to capture its error messages.
            self._resources.enter_context(
                patch('argparse._sys.stderr', self._stderr))
        except:
            self._resources.close()
            raise

    def tearDown(self):
        self._resources.close()
        super().tearDown()

    def test_config_file_good_path(self):
        # The default configuration file exists.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv', ['argv0', '--info']))
        # Patch default configuration file.
        tempdir = self._resources.enter_context(temporary_directory())
        ini_path = os.path.join(tempdir, 'client.ini')
        shutil.copy(
            resource_filename('systemimage.data', 'client.ini'), tempdir)
        self._resources.enter_context(
            patch('systemimage.main.DEFAULT_CONFIG_FILE', ini_path))
        # Mock out the initialize() call so that the main() doesn't try to
        # create a log file in a non-existent system directory.
        self._resources.enter_context(patch('systemimage.main.initialize'))
        cli_main()
        self.assertEqual(config.config_file, ini_path)
        self.assertEqual(config.system.build_file, '/etc/ubuntu-build')

    def test_missing_default_config_file(self):
        # The default configuration file is missing.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv', ['argv0']))
        # Patch default configuration file.
        self._resources.enter_context(
            patch('systemimage.main.DEFAULT_CONFIG_FILE',
                  '/does/not/exist/client.ini'))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
            self._stderr.getvalue().splitlines()[-1],
            'Configuration file not found: /does/not/exist/client.ini')

    def test_missing_explicit_config_file(self):
        # An explicit configuration file given with -C is missing.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', '/does/not/exist.ini']))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
            self._stderr.getvalue().splitlines()[-1],
            'Configuration file not found: /does/not/exist.ini')

    def test_ensure_directories_exist(self):
        # The temporary and var directories are created if they don't exist.
        dir_1 = self._resources.enter_context(temporary_directory())
        dir_2 = self._resources.enter_context(temporary_directory())
        # Create a configuration file with directories that point to
        # non-existent locations.
        config_ini = os.path.join(dir_1, 'client.ini')
        with open(data_path('00.ini'), encoding='utf-8') as fp:
            template = fp.read()
        # These paths look something like they would on the real system.
        tmpdir = os.path.join(dir_2, 'tmp', 'system-image')
        vardir = os.path.join(dir_2, 'var', 'lib', 'system-image')
        configuration = template.format(tmpdir=tmpdir, vardir=vardir)
        with open(config_ini, 'wt', encoding='utf-8') as fp:
            fp.write(configuration)
        # Invoking main() creates the directories.
        self._resources.enter_context(patch(
            'systemimage.main.sys.argv',
            ['argv0', '-C', config_ini, '--info']))
        self.assertFalse(os.path.exists(tmpdir))
        cli_main()
        self.assertTrue(os.path.exists(tmpdir))

    def test_permissions(self):
        # LP: #1235975 - Various directories and files have unsafe
        # permissions.
        dir_1 = self._resources.enter_context(temporary_directory())
        dir_2 = self._resources.enter_context(temporary_directory())
        # Create a configuration file with directories that point to
        # non-existent locations.
        config_ini = os.path.join(dir_1, 'client.ini')
        with open(data_path('config_04.ini'), encoding='utf-8') as fp:
            template = fp.read()
        # These paths look something like they would on the real system.
        tmpdir = os.path.join(dir_2, 'tmp', 'system-image')
        vardir = os.path.join(dir_2, 'var', 'lib', 'system-image')
        configuration = template.format(tmpdir=tmpdir, vardir=vardir)
        with open(config_ini, 'w', encoding='utf-8') as fp:
            fp.write(configuration)
        # Invoking main() creates the directories.
        config = Configuration(config_ini)
        self.assertFalse(os.path.exists(config.system.tempdir))
        self.assertFalse(os.path.exists(config.system.logfile))
        self._resources.enter_context(patch(
            'systemimage.main.sys.argv',
            ['argv0', '-C', config_ini, '--info']))
        cli_main()
        mode = os.stat(config.system.tempdir).st_mode
        self.assertEqual(stat.filemode(mode), 'drwx--S---')
        mode = os.stat(os.path.dirname(config.system.logfile)).st_mode
        self.assertEqual(stat.filemode(mode), 'drwx--S---')
        mode = os.stat(config.system.logfile).st_mode
        self.assertEqual(stat.filemode(mode), '-rw-------')

    @configuration
    def test_info(self, config_d):
        # -i/--info gives information about the device, including the current
        # build number, channel, and device name.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--info']))
        # Set up the build number.
        touch_build(1701, TIMESTAMP)
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1701
            device name: nexus7
            channel: stable
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_info_last_update_channel_ini(self, config_d):
        # --info's last update date uses the mtime of channel.ini even when
        # /etc/ubuntu-build exists.
        channel_ini = os.path.join(config_d, 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_01.ini', head, tail)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--info']))
        # Set up the build number.
        config = Configuration(config_d)
        touch_build(1701)
        timestamp_1 = int(datetime(2011, 1, 8, 2, 3, 4).timestamp())
        os.utime(config.system.build_file, (timestamp_1, timestamp_1))
        timestamp_2 = int(datetime(2011, 8, 1, 5, 6, 7).timestamp())
        os.utime(channel_ini, (timestamp_2, timestamp_2))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1833
            device name: nexus7
            channel: proposed
            last update: 2011-08-01 05:06:07
            """))

    @configuration
    def test_info_last_update_date_fallback(self, config_d):
        # --info's last update date falls back to the mtime of
        # /etc/ubuntu-build when no channel.ini file exists.
        channel_ini = os.path.join(config_d, 'channel.ini')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--info']))
        # Set up the build number.
        config = Configuration(config_d)
        touch_build(1701)
        timestamp_1 = int(datetime(2011, 1, 8, 2, 3, 4).timestamp())
        os.utime(config.system.build_file, (timestamp_1, timestamp_1))
        self.assertFalse(os.path.exists(channel_ini))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1701
            device name: nexus7
            channel: stable
            last update: 2011-01-08 02:03:04
            """))

    @configuration
    def test_build_number(self, config_d):
        # -b/--build overrides the build number.
        touch_build(1701, TIMESTAMP)
        # Use --build to override the default build number.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d,
                   '--build', '20250801',
                   '--info']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20250801
            device name: nexus7
            channel: stable
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_device_name(self, config_d):
        # -d/--device overrides the device type.
        touch_build(1701, TIMESTAMP)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d,
                   '--device', 'phablet',
                   '--info']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1701
            device name: phablet
            channel: stable
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_channel_name(self, config_d):
        # -c/--channel overrides the channel.
        touch_build(1701, TIMESTAMP)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d,
                   '--channel', 'daily-proposed',
                   '--info']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1701
            device name: nexus7
            channel: daily-proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_channel_name_with_alias(self, config_d):
        # When the current channel has an alias, this is reflected in the
        # output for --info
        channel_ini = os.path.join(config_d, 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_05.ini', head, tail)
        touch_build(300, TIMESTAMP)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--info']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 300
            device name: nexus7
            channel: daily
            alias: saucy
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_all_overrides(self, config_d):
        # Use -b -d and -c together.
        touch_build(1701, TIMESTAMP)
        # Use --build to override the default build number.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d,
                   '-b', '20250801',
                   '-c', 'daily-proposed',
                   '-d', 'phablet',
                   '--info']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20250801
            device name: phablet
            channel: daily-proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_bad_build_number_override(self, config_d):
        # -b/--build requires an integer.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--build', 'bogus']))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
          self._stderr.getvalue().splitlines()[-1],
          'system-image-cli: error: -b/--build requires an integer: bogus')

    @configuration
    def test_channel_ini_override_build_number(self, config_d):
        # The channel.ini file can override the build number.
        copy('channel_01.ini', config_d, 'channel.ini')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '-i']))
        # Set up the build number.
        touch_build(1701, TIMESTAMP)
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1833
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_channel_ini_override_channel(self, config_d):
        # The channel.ini file can override the channel.
        channel_ini = os.path.join(config_d, 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_01.ini', head, tail)
        os.utime(channel_ini, (TIMESTAMP, TIMESTAMP))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '-i']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1833
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_switch_channel(self, config_d):
        # `system-image-cli --switch <channel>` is a convenience equivalent to
        # `system-image-cli -b 0 --channel <channel>`.
        touch_build(801, TIMESTAMP)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--switch', 'utopic-proposed',
                   '--info']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 0
            device name: nexus7
            channel: utopic-proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_switch_channel_with_overrides(self, config_d):
        # The use of --switch is a convenience only, and if -b and/or -c is
        # given explicitly, they override the convenience.
        touch_build(801, TIMESTAMP)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--switch', 'utopic-proposed',
                   '-b', '1', '-c', 'utopic', '--info']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1
            device name: nexus7
            channel: utopic
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_log_file(self, config_d):
        # Test that the system log file gets created and written.
        config = Configuration(config_d)
        self.assertFalse(os.path.exists(config.system.logfile))
        class FakeState:
            def __init__(self, candidate_filter):
                self.downloader = MagicMock()
            def __iter__(self):
                return self
            def __next__(self):
                raise StopIteration
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
            ['argv0', '-C', config_d]))
        self._resources.enter_context(
            patch('systemimage.main.State', FakeState))
        cli_main()
        self.assertTrue(os.path.exists(config.system.logfile))
        with open(config.system.logfile, encoding='utf-8') as fp:
            logged = fp.readlines()
        # Ignore any leading timestamp and the trailing newline.
        self.assertRegex(
            logged[0],
            r'\[systemimage\] [^(]+ \(\d+\) '
            r'running state machine \[stable/nexus7\]\n')
        self.assertRegex(
            logged[1],
            r'\[systemimage\] [^(]+ \(\d+\) '
            r'state machine finished\n')

    @configuration
    def test_log_file_permission_denied(self, config_d):
        # LP: #1301995 - some tests are run as non-root, meaning they don't
        # have access to the system log file.  Use a fallback in that case.
        config = Configuration(config_d)
        # Set the log file to read-only.
        system_log = Path(config.system.logfile)
        system_log.touch(0o444, exist_ok=False)
        # Mock the fallback cache directory location for testability.
        tmpdir = self._resources.enter_context(temporary_directory())
        self._resources.enter_context(
            patch('systemimage.logging.xdg_cache_home', tmpdir))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--dry-run']))
        cli_main()
        # There should now be nothing in the system log file, and something in
        # the fallback log file.
        self.assertEqual(system_log.stat().st_size, 0)
        fallback = Path(tmpdir) / 'system-image' / 'client.log'
        self.assertGreater(fallback.stat().st_size, 0)
        # The log file also has the expected permissions.
        self.assertEqual(stat.filemode(fallback.stat().st_mode), '-rw-------')

    @configuration
    def test_bad_filter_type(self, config_d):
        # --filter option where value is not `full` or `delta` is an error.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--filter', 'bogus']))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
            self._stderr.getvalue().splitlines()[-1],
            'system-image-cli: error: Bad filter type: bogus')

    @configuration
    def test_version_detail(self, config_d):
        # --info where channel.ini has [service]version_detail
        channel_ini = os.path.join(config_d, 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_03.ini', head, tail)
        os.utime(channel_ini, (TIMESTAMP, TIMESTAMP))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '-i']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1833
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            version ubuntu: 123
            version mako: 456
            version custom: 789
            """))

    @configuration
    def test_no_version_detail(self, config_d):
        # --info where channel.ini does not hav [service]version_detail
        channel_ini = os.path.join(config_d, 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_01.ini', head, tail)
        os.utime(channel_ini, (TIMESTAMP, TIMESTAMP))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '-i']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1833
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_state_machine_exceptions(self, config_d):
        # If an exception happens during the state machine run, the error is
        # logged and main exits with code 1.
        config = Configuration(config_d)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv', ['argv0', '-C', config_d]))
        # Making the cache directory unwritable is a good way to trigger a
        # crash.  Be sure to set it back though!
        with chmod(config.updater.cache_partition, 0):
            exit_code = cli_main()
        self.assertEqual(exit_code, 1)

    @configuration
    def test_state_machine_exceptions_dry_run(self, config_d):
        # Like above, but doing only a --dry-run.
        config = Configuration(config_d)
        # Making the cache directory unwritable is a good way to trigger a
        # crash.  Be sure to set it back though!
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--dry-run']))
        with chmod(config.updater.cache_partition, 0):
            exit_code = cli_main()
        self.assertEqual(exit_code, 1)


class TestCLIMainDryRun(ServerTestBase):
    INDEX_FILE = 'index_14.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_dry_run(self, config_d):
        # `system-image-cli --dry-run` prints the winning upgrade path.
        self._setup_server_keyrings()
        # We patch builtin print() rather than sys.stdout because the
        # latter can mess with pdb output should we need to trace through
        # the code.
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            resources.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', config_d, '--dry-run']))
            cli_main()
        self.assertEqual(capture.getvalue(),
                         'Upgrade path is 1200:1201:1304\n')

    @configuration
    def test_dry_run_no_update(self, config_d):
        # `system-image-cli --dry-run` when there are no updates available.
        self._setup_server_keyrings()
        # We patch builtin print() rather than sys.stdout because the
        # latter can mess with pdb output should we need to trace through
        # the code.
        capture = StringIO()
        # Set up the build number.
        touch_build(1701)
        with ExitStack() as resources:
            resources.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            resources.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', config_d, '--dry-run']))
            cli_main()
        self.assertEqual(capture.getvalue(), 'Already up-to-date\n')

    @configuration
    def test_dry_run_bad_channel(self, config_d):
        # `system-image-cli --dry-run --channel <bad-channel>` should say it's
        # already up-to-date.
        self._setup_server_keyrings()
        # We patch builtin print() rather than sys.stdout because the
        # latter can mess with pdb output should we need to trace through
        # the code.
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            # Use --build to override the default build number.
            resources.enter_context(
                patch('systemimage.main.sys.argv', [
                            'argv0', '-C', config_d,
                            '--channel', 'daily-proposed',
                            '--dry-run']))
            cli_main()
        self.assertEqual(capture.getvalue(), 'Already up-to-date\n')


class TestCLIMainDryRunAliases(ServerTestBase):
    INDEX_FILE = 'index_20.json'
    CHANNEL_FILE = 'channels_10.json'
    CHANNEL = 'daily'
    DEVICE = 'manta'

    @configuration
    def test_dry_run_with_channel_alias_switch(self, config_d):
        # `system-image-cli --dry-run` where the channel alias the device was
        # on got switched should include this information.
        self._setup_server_keyrings()
        channel_ini = os.path.join(config_d, 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_05.ini', head, tail)
        capture = StringIO()
        self._resources.enter_context(
            patch('builtins.print', partial(print, file=capture)))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--dry-run']))
        # Do not use self._resources to manage the check_output mock.  Because
        # of the nesting order of the @configuration decorator and the base
        # class's tearDown(), using self._resources causes the mocks to be
        # unwound in the wrong order, affecting future tests.
        with patch('systemimage.device.check_output', return_value='manta'):
            cli_main()
        self.assertEqual(
            capture.getvalue(),
            'Upgrade path is 200:201:304 (saucy -> tubular)\n')


class TestCLIListChannels(ServerTestBase):
    INDEX_FILE = 'index_20.json'
    CHANNEL_FILE = 'channels_10.json'
    CHANNEL = 'daily'
    DEVICE = 'manta'

    @configuration
    def test_list_channels(self, config_d):
        # `system-image-cli --list-channels` shows all available channels,
        # including aliases.
        self._setup_server_keyrings()
        channel_ini = os.path.join(config_d, 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_05.ini', head, tail)
        capture = StringIO()
        self._resources.enter_context(
            patch('builtins.print', partial(print, file=capture)))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--list-channels']))
        # Do not use self._resources to manage the check_output mock.  Because
        # of the nesting order of the @configuration decorator and the base
        # class's tearDown(), using self._resources causes the mocks to be
        # unwound in the wrong order, affecting future tests.
        with patch('systemimage.device.check_output', return_value='manta'):
            cli_main()
        self.assertMultiLineEqual(capture.getvalue(), dedent("""\
            Available channels:
                daily (alias for: tubular)
                saucy
                tubular
            """))

    @configuration
    def test_list_channels_exception(self, config_d):
        # If an exception occurs while getting the list of channels, we get a
        # non-zero exit status.
        self._setup_server_keyrings()
        channel_ini = os.path.join(config_d, 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_05.ini', head, tail)
        capture = StringIO()
        self._resources.enter_context(
            patch('builtins.print', partial(print, file=capture)))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--list-channels']))
        # Do not use self._resources to manage the check_output mock.  Because
        # of the nesting order of the @configuration decorator and the base
        # class's tearDown(), using self._resources causes the mocks to be
        # unwound in the wrong order, affecting future tests.
        with ExitStack() as more:
            more.enter_context(
                patch('systemimage.device.check_output', return_value='manta'))
            more.enter_context(
                patch('systemimage.state.State._get_channel',
                      side_effect=RuntimeError))
            status = cli_main()
        self.assertEqual(status, 1)


class TestCLIFilters(ServerTestBase):
    INDEX_FILE = 'index_15.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    maxDiff = None

    @configuration
    def test_filter_full(self, config_d):
        # With --filter=full, only full updates will be considered.
        self._setup_server_keyrings()
        # We patch builtin print() rather than sys.stdout because the
        # latter can mess with pdb output should we need to trace through
        # the code.
        capture = StringIO()
        # Set up the build number.
        touch_build(100)
        with ExitStack() as resources:
            resources.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            resources.enter_context(
                patch('systemimage.main.sys.argv', [
                            'argv0', '-C', config_d, '--dry-run',
                            '--filter', 'full']))
            cli_main()
        self.assertMultiLineEqual(capture.getvalue(), 'Already up-to-date\n')

    @configuration
    def test_filter_delta(self, config_d):
        # With --filter=delta, only delta updates will be considered.
        self._setup_server_keyrings()
        # We patch builtin print() rather than sys.stdout because the
        # latter can mess with pdb output should we need to trace through
        # the code.
        capture = StringIO()
        # Set up the build number.
        touch_build(100)
        with ExitStack() as resources:
            resources.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            resources.enter_context(
                patch('systemimage.main.sys.argv', [
                            'argv0', '-C', config_d, '--dry-run',
                            '--filter', 'delta']))
            cli_main()
        self.assertMultiLineEqual(capture.getvalue(), 'Upgrade path is 1600\n')


class TestCLIDuplicateDestinations(ServerTestBase):
    INDEX_FILE = 'index_23.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_duplicate_destinations(self, config_d):
        # index_23.json has the bug we saw in the wild in LP: #1250181.
        # There, the server erroneously included a data file twice in two
        # different images.  This can't happen and indicates a server
        # problem.  The client must refuse to upgrade in this case, by raising
        # an exception.
        self._setup_server_keyrings()
        with ExitStack() as resources:
            resources.enter_context(
                patch('systemimage.main.sys.argv', ['argv0', '-C', config_d]))
            exit_code = cli_main()
        self.assertEqual(exit_code, 1)
        # 2013-11-12 BAW: IWBNI we could assert something about the log
        # output, since that contains a display of the duplicate destination
        # paths and the urls that map to them, but that's difficult for
        # several reasons, including that we can't really mock the log
        # instance (it's a local variable to main(), and the output will
        # contain stack traces and random paths.  I bet we could hack
        # something in with doctest.OutputChecker.check_output(), but I'm not
        # sure it's worth it.


class TestCLINoReboot(ServerTestBase):
    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_10.json'
    CHANNEL = 'daily'
    DEVICE = 'manta'

    @configuration
    def test_no_reboot(self, config_d):
        # `system-image-cli --no-reboot` downloads everything but does not
        # reboot into recovery.
        self._setup_server_keyrings()
        capture = StringIO()
        self._resources.enter_context(
            patch('builtins.print', partial(print, file=capture)))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--no-reboot',
                   '-b', 0, '-c', 'daily']))
        mock = self._resources.enter_context(
            patch('systemimage.reboot.Reboot.reboot'))
        # Do not use self._resources to manage the check_output mock.  Because
        # of the nesting order of the @configuration decorator and the base
        # class's tearDown(), using self._resources causes the mocks to be
        # unwound in the wrong order, affecting future tests.
        with patch('systemimage.device.check_output', return_value='manta'):
            cli_main()
        # The reboot method was never called.
        self.assertFalse(mock.called)
        # All the expected files should be downloaded.
        self.assertEqual(set(os.listdir(config.updater.data_partition)), set([
            'blacklist.tar.xz',
            'blacklist.tar.xz.asc',
            ]))
        self.assertEqual(set(os.listdir(config.updater.cache_partition)), set([
            '5.txt',
            '5.txt.asc',
            '6.txt',
            '6.txt.asc',
            '7.txt',
            '7.txt.asc',
            'device-signing.tar.xz',
            'device-signing.tar.xz.asc',
            'image-master.tar.xz',
            'image-master.tar.xz.asc',
            'image-signing.tar.xz',
            'image-signing.tar.xz.asc',
            'ubuntu_command',
            ]))
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, """\
load_keyring image-master.tar.xz image-master.tar.xz.asc
load_keyring image-signing.tar.xz image-signing.tar.xz.asc
load_keyring device-signing.tar.xz device-signing.tar.xz.asc
format system
mount system
update 6.txt 6.txt.asc
update 7.txt 7.txt.asc
update 5.txt 5.txt.asc
unmount system
""")

    @configuration
    def test_g(self, config_d):
        # `system-image-cli -g` downloads everything but does not reboot into
        # recovery.
        self._setup_server_keyrings()
        capture = StringIO()
        self._resources.enter_context(
            patch('builtins.print', partial(print, file=capture)))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '-g', '-b', 0, '-c', 'daily']))
        mock = self._resources.enter_context(
            patch('systemimage.reboot.Reboot.reboot'))
        # Do not use self._resources to manage the check_output mock.  Because
        # of the nesting order of the @configuration decorator and the base
        # class's tearDown(), using self._resources causes the mocks to be
        # unwound in the wrong order, affecting future tests.
        with patch('systemimage.device.check_output', return_value='manta'):
            cli_main()
        # The reboot method was never called.
        self.assertFalse(mock.called)
        # All the expected files should be downloaded.
        self.assertEqual(set(os.listdir(config.updater.data_partition)), set([
            'blacklist.tar.xz',
            'blacklist.tar.xz.asc',
            ]))
        self.assertEqual(set(os.listdir(config.updater.cache_partition)), set([
            '5.txt',
            '5.txt.asc',
            '6.txt',
            '6.txt.asc',
            '7.txt',
            '7.txt.asc',
            'device-signing.tar.xz',
            'device-signing.tar.xz.asc',
            'image-master.tar.xz',
            'image-master.tar.xz.asc',
            'image-signing.tar.xz',
            'image-signing.tar.xz.asc',
            'ubuntu_command',
            ]))
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, """\
load_keyring image-master.tar.xz image-master.tar.xz.asc
load_keyring image-signing.tar.xz image-signing.tar.xz.asc
load_keyring device-signing.tar.xz device-signing.tar.xz.asc
format system
mount system
update 6.txt 6.txt.asc
update 7.txt 7.txt.asc
update 5.txt 5.txt.asc
unmount system
""")

    @configuration
    def test_rerun_after_no_reboot_reboots(self, config_d):
        # Running system-image-cli again after a `system-image-cli -g` does
        # not download anything the second time, but does issue a reboot.
        self._setup_server_keyrings()
        capture = StringIO()
        self._resources.enter_context(
            patch('builtins.print', partial(print, file=capture)))
        mock = self._resources.enter_context(
            patch('systemimage.reboot.Reboot.reboot'))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '-g', '-b', 0, '-c', 'daily']))
        # Do not use self._resources to manage the check_output mock.  Because
        # of the nesting order of the @configuration decorator and the base
        # class's tearDown(), using self._resources causes the mocks to be
        # unwound in the wrong order, affecting future tests.
        with patch('systemimage.device.check_output', return_value='manta'):
            cli_main()
        # The reboot method was never called.
        self.assertFalse(mock.called)
        # To prove nothing gets downloaded the second time, actually delete
        # the data files from the server.
        shutil.rmtree(os.path.join(self._serverdir, '3'))
        shutil.rmtree(os.path.join(self._serverdir, '4'))
        shutil.rmtree(os.path.join(self._serverdir, '5'))
        with patch('systemimage.main.sys.argv',
                   ['argv0', '-C', config_d, '-b', 0, '-c', 'daily']):
            cli_main()
        # The reboot method was never called.
        self.assertTrue(mock.called)


class TestCLIFactoryReset(unittest.TestCase):
    """Test the --factory-reset option for factory resets."""

    @configuration
    def test_factory_reset(self, config_d):
        # system-image-cli --factory-reset
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            mock = resources.enter_context(
                patch('systemimage.reboot.Reboot.reboot'))
            resources.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', config_d, '--factory-reset']))
            cli_main()
        # A reboot was issued.
        self.assertTrue(mock.called)
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, dedent("""\
            format data
            """))


class TestCLISettings(unittest.TestCase):
    """Test settings command line options."""

    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        try:
            self._stdout = StringIO()
            self._stderr = StringIO()
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            self._resources.enter_context(
                patch('builtins.print', partial(print, file=self._stdout)))
            # Patch argparse's stderr to capture its error messages.
            self._resources.enter_context(
                patch('argparse._sys.stderr', self._stderr))
        except:
            self._resources.close()
            raise

    def tearDown(self):
        self._resources.close()
        super().tearDown()

    @configuration
    def test_show_settings(self, config_d):
        # `system-image-cli --show-settings` shows all the keys and values in
        # sorted  order by alphanumeric key name.
        settings = Settings()
        settings.set('peart', 'neil')
        settings.set('lee', 'geddy')
        settings.set('lifeson', 'alex')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--show-settings']))
        cli_main()
        self.assertMultiLineEqual(self._stdout.getvalue(), dedent("""\
            lee=geddy
            lifeson=alex
            peart=neil
            """))

    @configuration
    def test_get_key(self, config_d):
        # `system-image-cli --get key` prints the key's value.
        settings = Settings()
        settings.set('ant', 'aunt')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--get', 'ant']))
        cli_main()
        self.assertMultiLineEqual(self._stdout.getvalue(), dedent("""\
            aunt
            """))

    @configuration
    def test_get_keys(self, config_d):
        # `--get key` can be used multiple times.
        settings = Settings()
        settings.set('s', 'saucy')
        settings.set('t', 'trusty')
        settings.set('u', 'utopic')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d,
                   '--get', 's', '--get', 'u', '--get', 't']))
        cli_main()
        self.assertMultiLineEqual(self._stdout.getvalue(), dedent("""\
            saucy
            utopic
            trusty
            """))

    @configuration
    def test_get_missing_key(self, config_d):
        # Since by definition a missing key has a default value, you can get
        # missing keys.  Note that `auto_download` is the one weirdo.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C',  config_d,
                   '--get', 'missing', '--get', 'auto_download']))
        cli_main()
        # This produces a blank line, since `missing` returns the empty
        # string.  For better readability, don't indent the results.
        self.assertMultiLineEqual(self._stdout.getvalue(), """\

1
""")

    @configuration
    def test_set_key(self, config_d):
        # `system-image-cli --set key=value` sets a key/value pair.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--set', 'bass=4']))
        cli_main()
        self.assertEqual(Settings().get('bass'), '4')

    @configuration
    def test_change_key(self, config_d):
        # `--set key=value` changes an existing key's value.
        settings = Settings()
        settings.set('a', 'ant')
        settings.set('b', 'bee')
        settings.set('c', 'cat')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--set', 'b=bat']))
        cli_main()
        self.assertEqual(settings.get('a'), 'ant')
        self.assertEqual(settings.get('b'), 'bat')
        self.assertEqual(settings.get('c'), 'cat')

    @configuration
    def test_set_keys(self, config_d):
        # `--set key=value` can be used multiple times.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d,
                   '--set', 'a=ant',
                   '--set', 'b=bee',
                   '--set', 'c=cat']))
        cli_main()
        settings = Settings()
        self.assertEqual(settings.get('a'), 'ant')
        self.assertEqual(settings.get('b'), 'bee')
        self.assertEqual(settings.get('c'), 'cat')

    @configuration
    def test_del_key(self, config_d):
        # `system-image-cli --del key` removes a key from the database.
        settings = Settings()
        settings.set('ant', 'insect')
        settings.set('bee', 'insect')
        settings.set('cat', 'mammal')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--del', 'bee']))
        cli_main()
        settings = Settings()
        self.assertEqual(settings.get('ant'), 'insect')
        self.assertEqual(settings.get('cat'), 'mammal')
        # When the key is missing, the empty string is the default.
        self.assertEqual(settings.get('bee'), '')

    @configuration
    def test_del_keys(self, config_d):
        # `--del key` can be used multiple times.
        settings = Settings()
        settings.set('ant', 'insect')
        settings.set('bee', 'insect')
        settings.set('cat', 'mammal')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--del', 'bee', '--del', 'cat']))
        cli_main()
        settings = Settings()
        self.assertEqual(settings.get('ant'), 'insect')
        # When the key is missing, the empty string is the default.
        self.assertEqual(settings.get('cat'), '')
        self.assertEqual(settings.get('bee'), '')

    @configuration
    def test_del_missing_key(self, config_d):
        # When asked to delete a key that's not in the database, nothing
        # much happens.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d, '--del', 'missing']))
        cli_main()
        self.assertEqual(Settings().get('missing'), '')

    @configuration
    def test_mix_and_match(self, config_d):
        # Because argument order is not preserved, and any semantics for
        # mixing and matching database arguments would be arbitrary, it is not
        # allowed to mix them.
        capture = StringIO()
        self._resources.enter_context(
            patch('builtins.print', partial(print, file=capture)))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', config_d,
                   '--set', 'c=cat', '--del', 'bee', '--get', 'dog']))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
            self._stderr.getvalue().splitlines()[-1],
            'system-image-cli: error: Cannot mix and match settings arguments')


class TestDBusMain(unittest.TestCase):
    def setUp(self):
        self._stack = ExitStack()
        try:
            old_ini = SystemImagePlugin.controller.ini_path
            self._stack.callback(
                setattr, SystemImagePlugin.controller, 'ini_path', old_ini)
            self.tmpdir = self._stack.enter_context(temporary_directory())
            template = resource_bytes(
                'systemimage.tests.data', 'config_04.ini').decode('utf-8')
            self.ini_path = os.path.join(self.tmpdir, 'client.ini')
            with open(self.ini_path, 'w', encoding='utf-8') as fp:
                print(template.format(tmpdir=self.tmpdir, vardir=self.tmpdir),
                      file=fp)
            SystemImagePlugin.controller.ini_path = self.ini_path
            SystemImagePlugin.controller.set_mode()
        except:
            self._stack.close()
            raise

    def tearDown(self):
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        iface = dbus.Interface(service, 'com.canonical.SystemImage')
        iface.Exit()
        self._stack.close()

    def _activate(self):
        # Start the D-Bus service.
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        iface = dbus.Interface(service, 'com.canonical.SystemImage')
        return iface.Info()

    def test_service_exits(self):
        # The dbus service automatically exits after a set amount of time.
        #
        # Nothing has been spawned yet.
        self.assertIsNone(find_dbus_process(self.ini_path))
        self._activate()
        process = find_dbus_process(self.ini_path)
        self.assertTrue(process.is_running())
        # Now wait for the process to self-terminate.  If this times out
        # before the process exits, a TimeoutExpired exception will be
        # raised.  Let this propagate up as a test failure.
        process.wait(timeout=6)
        self.assertFalse(process.is_running())

    def test_service_keepalive(self):
        # Proactively calling methods on the service keeps it alive.
        self.assertIsNone(find_dbus_process(self.ini_path))
        self._activate()
        process = find_dbus_process(self.ini_path)
        self.assertTrue(process.is_running())
        # Normally the process would exit after 3 seconds, but we'll keep it
        # alive for a bit.
        for i in range(3):
            self._activate()
            time.sleep(2)
        self.assertTrue(process.is_running())

    def test_channel_ini_override(self):
        # An optional channel.ini can override the build number and channel.
        #
        # The config.ini file names the `stable` channel.  Let's create an
        # ubuntu-build file with a fake version number.
        config = Configuration(self.ini_path)
        with open(config.system.build_file, 'w', encoding='utf-8') as fp:
            print(33, file=fp)
        # Now, write a channel.ini file to override both of these.
        dirname = os.path.dirname(self.ini_path)
        copy('channel_04.ini', dirname, 'channel.ini')
        info = self._activate()
        # The build number.
        self.assertEqual(info[0], 1)
        # The channel
        self.assertEqual(info[2], 'saucy')

    def test_temp_directory(self):
        # The temporary directory gets created if it doesn't exist.
        config = Configuration(self.ini_path)
        # The temporary directory may have already been created via the
        # .set_mode() call in the setUp().  That invokes a 'stopper' for the
        # -dbus process, which has the perverse effect of first D-Bus
        # activating the process, and thus creating the temporary directory
        # before calling .Exit().  However, due to timing issues, it's
        # possible we get here before the process was ever started, and thus
        # the daemon won't be killed.  Conditionally deleting it now will
        # allow the .Info() call below to re-active the process and thus
        # re-create the directory.
        try:
            shutil.rmtree(config.system.tempdir)
        except FileNotFoundError:
            pass
        self.assertFalse(os.path.exists(config.system.tempdir))
        self._activate()
        self.assertTrue(os.path.exists(config.system.tempdir))

    def test_permissions(self):
        # LP: #1235975 - The created tempdir had unsafe permissions.
        config = Configuration(self.ini_path)
        # See above.
        try:
            shutil.rmtree(config.system.tempdir)
        except FileNotFoundError:
            pass
        safe_remove(config.system.logfile)
        self._activate()
        mode = os.stat(config.system.tempdir).st_mode
        self.assertEqual(stat.filemode(mode), 'drwx--S---')
        mode = os.stat(os.path.dirname(config.system.logfile)).st_mode
        self.assertEqual(stat.filemode(mode), 'drwx--S---')
        mode = os.stat(config.system.logfile).st_mode
        self.assertEqual(stat.filemode(mode), '-rw-------')

    def test_single_instance(self):
        # Only one instance of the system-image-dbus service is allowed to
        # remain active on a single system bus.
        self.assertIsNone(find_dbus_process(self.ini_path))
        self._activate()
        proc = find_dbus_process(self.ini_path)
        # Attempt to start a second process on the same system bus.
        env = dict(
            DBUS_SYSTEM_BUS_ADDRESS=os.environ['DBUS_SYSTEM_BUS_ADDRESS'])
        coverage_env = os.environ.get('COVERAGE_PROCESS_START')
        if coverage_env is not None:
            env['COVERAGE_PROCESS_START'] = coverage_env
        args = (sys.executable, '-m', 'systemimage.testing.service',
                '-C', self.ini_path)
        second = subprocess.Popen(args, universal_newlines=True, env=env)
        # Allow a TimeoutExpired exception to fail the test.
        try:
            code = second.wait(timeout=10)
        except subprocess.TimeoutExpired:
            second.kill()
            second.communicate()
            raise
        self.assertNotEqual(second.pid, proc.pid)
        self.assertEqual(code, 2)
