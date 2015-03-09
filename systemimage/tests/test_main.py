# Copyright (C) 2013-2015 Canonical Ltd.
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
    'TestCLIFactoryReset',
    'TestCLIFilters',
    'TestCLIListChannels',
    'TestCLIMain',
    'TestCLIMainDryRun',
    'TestCLIMainDryRunAliases',
    'TestCLINoReboot',
    'TestCLIProductionReset',
    'TestCLIProgress',
    'TestCLISettings',
    'TestCLISignatures',
    'TestDBusMain',
    'TestDBusMainNoConfigD',
    ]


import os
import sys
import dbus
import json
import stat
import time
import shutil
import unittest
import subprocess

from contextlib import ExitStack, contextmanager
from datetime import datetime
from dbus.exceptions import DBusException
from functools import partial
from io import StringIO
from pathlib import Path
from systemimage.config import Configuration, config
from systemimage.helpers import safe_remove
from systemimage.main import main as cli_main
from systemimage.settings import Settings
from systemimage.testing.helpers import (
    ServerTestBase, chmod, configuration, copy, data_path, find_dbus_process,
    sign, temporary_directory, touch_build, wait_for_service)
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


def machine_id(mid):
    with ExitStack() as resources:
        tempdir = resources.enter_context(temporary_directory())
        path = os.path.join(tempdir, 'machine-id')
        with open(path, 'w', encoding='utf-8') as fp:
            print(mid, file=fp)
        resources.enter_context(
            patch('systemimage.helpers.UNIQUE_MACHINE_ID_FILES', [path]))
        return resources.pop_all()


def capture_print(fp):
    return patch('builtins.print', partial(print, file=fp))


def argv(*args):
    args = list(args)
    args.insert(0, 'argv0')
    with ExitStack() as resources:
        resources.enter_context(patch('systemimage.main.sys.argv', args))
        # We need a fresh global Configuration object to mimic what the
        # command line script would see.
        resources.enter_context(
            patch('systemimage.config._config', Configuration()))
        return resources.pop_all()


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
            self._resources.enter_context(capture_print(self._stdout))
            # Patch argparse's stderr to capture its error messages.
            self._resources.enter_context(
                patch('argparse._sys.stderr', self._stderr))
            self._resources.push(
                machine_id('feedfacebeefbacafeedfacebeefbaca'))
        except:
            self._resources.close()
            raise

    def tearDown(self):
        self._resources.close()
        super().tearDown()

    def test_config_directory_good_path(self):
        # The default configuration directory exists.
        self._resources.enter_context(argv('--info'))
        # Patch default configuration directory.
        tempdir = self._resources.enter_context(temporary_directory())
        copy('main.config_01.ini', tempdir, '00_config.ini')
        self._resources.enter_context(
            patch('systemimage.main.DEFAULT_CONFIG_D', tempdir))
        # Mock out the initialize() call so that the main() doesn't try to
        # create a log file in a non-existent system directory.
        self._resources.enter_context(patch('systemimage.main.initialize'))
        cli_main()
        self.assertEqual(config.config_d, tempdir)
        self.assertEqual(config.channel, 'special')

    def test_missing_default_config_directory(self):
        # The default configuration directory is missing.
        self._resources.enter_context(argv())
        # Patch default configuration directory.
        self._resources.enter_context(
            patch('systemimage.main.DEFAULT_CONFIG_D', '/does/not/exist'))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
            self._stderr.getvalue().splitlines()[-1],
            'Configuration directory not found: /does/not/exist')

    def test_missing_explicit_config_directory(self):
        # An explicit configuration directory given with -C is missing.
        self._resources.enter_context(argv('-C', '/does/not/exist'))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
            self._stderr.getvalue().splitlines()[-1],
            'Configuration directory not found: /does/not/exist')

    def test_ensure_directories_exist(self):
        # The temporary and var directories are created if they don't exist.
        dir_1 = self._resources.enter_context(temporary_directory())
        dir_2 = self._resources.enter_context(temporary_directory())
        # Create a configuration file with directories that point to
        # non-existent locations.
        config_ini = os.path.join(dir_1, '00_config.ini')
        with open(data_path('00.ini'), encoding='utf-8') as fp:
            template = fp.read()
        # These paths look something like they would on the real system.
        tmpdir = os.path.join(dir_2, 'tmp', 'system-image')
        vardir = os.path.join(dir_2, 'var', 'lib', 'system-image')
        configuration = template.format(tmpdir=tmpdir, vardir=vardir)
        with open(config_ini, 'wt', encoding='utf-8') as fp:
            fp.write(configuration)
        # Invoking main() creates the directories.
        self._resources.enter_context(argv('-C', dir_1, '--info'))
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
        config_ini = os.path.join(dir_1, '00_config.ini')
        with open(data_path('00.ini'), encoding='utf-8') as fp:
            template = fp.read()
        # These paths look something like they would on the real system.
        tmpdir = os.path.join(dir_2, 'tmp', 'system-image')
        vardir = os.path.join(dir_2, 'var', 'lib', 'system-image')
        configuration = template.format(tmpdir=tmpdir, vardir=vardir)
        with open(config_ini, 'w', encoding='utf-8') as fp:
            fp.write(configuration)
        # Invoking main() creates the directories.
        config = Configuration(dir_1)
        self.assertFalse(os.path.exists(config.system.tempdir))
        self.assertFalse(os.path.exists(config.system.logfile))
        self._resources.enter_context(argv('-C', dir_1, '--info'))
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
        touch_build(1701, TIMESTAMP)
        self._resources.enter_context(argv('-C', config_d, '--info'))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1701
            device name: nexus7
            channel: stable
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_info_last_update_timestamps(self, config_d):
        # --info's last update date uses the latest mtime of the files in the
        # config.d directory.
        copy('main.config_02.ini', config_d, '00_config.ini')
        copy('main.config_02.ini', config_d, '01_config.ini')
        copy('main.config_02.ini', config_d, '02_config.ini')
        # Give the default ini file an even earlier timestamp.
        timestamp_0 = int(datetime(2010, 11, 8, 2, 3, 4).timestamp())
        touch_build(1701, timestamp_0)
        # Make the 01 ini file the latest.
        timestamp_1 = int(datetime(2011, 1, 8, 2, 3, 4).timestamp())
        os.utime(os.path.join(config_d, '00_config.ini'),
                 (timestamp_1, timestamp_1))
        os.utime(os.path.join(config_d, '02_config.ini'),
                 (timestamp_1, timestamp_1))
        timestamp_2 = int(datetime(2011, 8, 1, 5, 6, 7).timestamp())
        os.utime(os.path.join(config_d, '01_config.ini'),
                 (timestamp_2, timestamp_2))
        self._resources.enter_context(argv('-C', config_d, '--info'))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1701
            device name: nexus7
            channel: proposed
            last update: 2011-08-01 05:06:07
            """))

    @configuration
    def test_build_number(self, config_d):
        # -b/--build overrides the build number.
        touch_build(1701, TIMESTAMP)
        # Use --build to override the default build number.
        self._resources.enter_context(
            argv('-C', config_d, '--build', '20250801', '--info'))
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
            argv('-C', config_d, '--device', 'phablet', '--info'))
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
            argv('-C', config_d, '--channel', 'daily-proposed', '--info'))
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
        copy('main.config_03.ini', config_d, '01_config.ini')
        touch_build(300, TIMESTAMP)
        self._resources.enter_context(argv('-C', config_d, '--info'))
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
            argv('-C', config_d,
                 '-b', '20250801',
                 '-c', 'daily-proposed',
                 '-d', 'phablet',
                 '--info'))
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
        self._resources.enter_context(argv('-C', config_d, '--build', 'bogus'))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
          self._stderr.getvalue().splitlines()[-1],
          'system-image-cli: error: -b/--build requires an integer: bogus')

    @configuration
    def test_switch_channel(self, config_d):
        # `system-image-cli --switch <channel>` is a convenience equivalent to
        # `system-image-cli -b 0 --channel <channel>`.
        touch_build(801, TIMESTAMP)
        self._resources.enter_context(
            argv('-C', config_d, '--switch', 'utopic-proposed', '--info'))
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
            argv('-C', config_d, '--switch', 'utopic-proposed',
                 '-b', '1', '-c', 'utopic', '--info'))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1
            device name: nexus7
            channel: utopic
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_log_file(self, config):
        # Test that the system log file gets created and written.
        self.assertFalse(os.path.exists(config.system.logfile))
        class FakeState:
            def __init__(self, candidate_filter):
                self.downloader = MagicMock()
            def __iter__(self):
                return self
            def __next__(self):
                raise StopIteration
        self._resources.enter_context(argv('-C', config.config_d))
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

    @unittest.skipIf(os.getuid() == 0, 'Test cannot succeed when run as root')
    @configuration
    def test_log_file_permission_denied(self, config):
        # LP: #1301995 - some tests are run as non-root, meaning they don't
        # have access to the system log file.  Use a fallback in that case.
        # Set the log file to read-only.
        system_log = Path(config.system.logfile)
        system_log.touch(0o444, exist_ok=False)
        # Mock the fallback cache directory location for testability.
        tmpdir = self._resources.enter_context(temporary_directory())
        self._resources.enter_context(
            patch('systemimage.logging.xdg_cache_home', tmpdir))
        self._resources.enter_context(argv('-C', config.config_d, '--dry-run'))
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
            argv('-C', config_d, '--filter', 'bogus'))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
            self._stderr.getvalue().splitlines()[-1],
            'system-image-cli: error: Bad filter type: bogus')

    @configuration
    def test_version_detail(self, config_d):
        # --info where a config file has [service]version_detail.
        copy('main.config_04.ini', config_d, '01_config.ini')
        touch_build(1933, TIMESTAMP)
        self._resources.enter_context(argv('-C', config_d, '-i'))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1933
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            version ubuntu: 123
            version mako: 456
            version custom: 789
            """))

    @configuration
    def test_no_version_detail(self, config_d):
        # --info where there is no [service]version_detail setting.
        copy('main.config_02.ini', config_d, '01_config.ini')
        touch_build(1933, TIMESTAMP)
        self._resources.enter_context(argv('-C', config_d, '-i'))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 1933
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_state_machine_exceptions(self, config):
        # If an exception happens during the state machine run, the error is
        # logged and main exits with code 1.
        self._resources.enter_context(argv('-C', config.config_d))
        # Making the cache directory unwritable is a good way to trigger a
        # crash.  Be sure to set it back though!
        with chmod(config.updater.cache_partition, 0):
            exit_code = cli_main()
        self.assertEqual(exit_code, 1)

    @configuration
    def test_state_machine_exceptions_dry_run(self, config):
        # Like above, but doing only a --dry-run.
        self._resources.enter_context(argv('-C', config.config_d, '--dry-run'))
        with chmod(config.updater.cache_partition, 0):
            exit_code = cli_main()
        self.assertEqual(exit_code, 1)


class TestCLIMainDryRun(ServerTestBase):
    INDEX_FILE = 'main.index_01.json'
    CHANNEL_FILE = 'main.channels_01.json'
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
            resources.enter_context(capture_print(capture))
            resources.push(machine_id('0000000000000000aaaaaaaaaaaaaaaa'))
            resources.enter_context(argv('-C', config_d, '--dry-run'))
            cli_main()
        self.assertEqual(
            capture.getvalue(), """\
Upgrade path is 1200:1201:1304
Target phase: 12%
""")

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
            resources.enter_context(capture_print(capture))
            resources.enter_context(argv('-C', config_d, '--dry-run'))
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
            resources.enter_context(capture_print(capture))
            # Use --build to override the default build number.
            resources.enter_context(
                argv('-C', config_d,
                     '--channel', 'daily-proposed',
                     '--dry-run'))
            cli_main()
        self.assertEqual(capture.getvalue(), 'Already up-to-date\n')

    @configuration
    def test_percentage(self, config_d):
        # --percentage overrides the device's target percentage.
        self._setup_server_keyrings()
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(capture_print(capture))
            resources.push(machine_id('0000000000000000aaaaaaaaaaaaaaaa'))
            resources.enter_context(argv('-C', config_d, '--dry-run'))
            cli_main()
        self.assertEqual(
            capture.getvalue(), """\
Upgrade path is 1200:1201:1304
Target phase: 12%
""")
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(capture_print(capture))
            resources.push(machine_id('0000000000000000aaaaaaaaaaaaaaaa'))
            resources.enter_context(
                argv('-C', config_d, '--dry-run', '--percentage', '81'))
            cli_main()
        self.assertEqual(
            capture.getvalue(), """\
Upgrade path is 1200:1201:1304
Target phase: 81%
""")

    @configuration
    def test_p(self, config_d):
        # -p overrides the device's target percentage.
        self._setup_server_keyrings()
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(capture_print(capture))
            resources.push(machine_id('0000000000000000aaaaaaaaaaaaaaaa'))
            resources.enter_context(argv('-C', config_d, '--dry-run'))
            cli_main()
        self.assertEqual(
            capture.getvalue(), """\
Upgrade path is 1200:1201:1304
Target phase: 12%
""")
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(capture_print(capture))
            resources.push(machine_id('0000000000000000aaaaaaaaaaaaaaaa'))
            resources.enter_context(
                argv('-C', config_d, '--dry-run', '-p', '81'))
            cli_main()
        self.assertEqual(
            capture.getvalue(), """\
Upgrade path is 1200:1201:1304
Target phase: 81%
""")

    @configuration
    def test_crazy_p(self, config_d):
        # --percentage/-p value is floored at 0% and ceilinged at 100%.
        self._setup_server_keyrings()
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(capture_print(capture))
            resources.push(machine_id('0000000000000000aaaaaaaaaaaaaaaa'))
            resources.enter_context(
                argv('-C', config_d, '--dry-run', '-p', '10000'))
            cli_main()
        self.assertEqual(
            capture.getvalue(), """\
Upgrade path is 1200:1201:1304
Target phase: 100%
""")
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(capture_print(capture))
            resources.push(machine_id('0000000000000000aaaaaaaaaaaaaaaa'))
            resources.enter_context(
                argv('-C', config_d, '--dry-run', '-p', '-10'))
            cli_main()
        self.assertEqual(
            capture.getvalue(), """\
Upgrade path is 1200:1201:1304
Target phase: 0%
""")


class TestCLIMainDryRunAliases(ServerTestBase):
    INDEX_FILE = 'main.index_02.json'
    CHANNEL_FILE = 'main.channels_02.json'
    CHANNEL = 'daily'
    DEVICE = 'manta'

    @configuration
    def test_dry_run_with_channel_alias_switch(self, config_d):
        # `system-image-cli --dry-run` where the channel alias the device was
        # on got switched should include this information.
        self._setup_server_keyrings()
        copy('main.config_05.ini', config_d, '01_config.ini')
        capture = StringIO()
        # Do not use self._resources to manage the check_output mock.  Because
        # of the nesting order of the @configuration decorator and the base
        # class's tearDown(), using self._resources causes the mocks to be
        # unwound in the wrong order, affecting future tests.
        with ExitStack() as resources:
            resources.enter_context(capture_print(capture))
            resources.enter_context(argv('-C', config_d, '--dry-run'))
            # Patch the machine id.
            resources.push(machine_id('0000000000000000aaaaaaaaaaaaaaaa'))
            resources.enter_context(
                patch('systemimage.device.check_output', return_value='manta'))
            cli_main()
        self.assertEqual(
            capture.getvalue(), """\
Upgrade path is 200:201:304 (saucy -> tubular)
Target phase: 25%
""")


class TestCLIListChannels(ServerTestBase):
    INDEX_FILE = 'main.index_02.json'
    CHANNEL_FILE = 'main.channels_02.json'
    CHANNEL = 'daily'
    DEVICE = 'manta'

    @configuration
    def test_list_channels(self, config_d):
        # `system-image-cli --list-channels` shows all available channels,
        # including aliases.
        self._setup_server_keyrings()
        copy('main.config_05.ini', config_d, '01_config.ini')
        capture = StringIO()
        self._resources.enter_context(capture_print(capture))
        self._resources.enter_context(argv('-C', config_d, '--list-channels'))
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
        copy('main.config_05.ini', config_d, '01_config.ini')
        capture = StringIO()
        self._resources.enter_context(capture_print(capture))
        self._resources.enter_context(argv('-C', config_d, '--list-channels'))
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
    INDEX_FILE = 'main.index_03.json'
    CHANNEL_FILE = 'main.channels_03.json'
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
            resources.enter_context(capture_print(capture))
            resources.enter_context(
                argv('-C', config_d, '--dry-run', '--filter', 'full'))
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
            resources.enter_context(capture_print(capture))
            resources.enter_context(
                argv('-C', config_d, '--dry-run', '--filter', 'delta'))
            resources.push(machine_id('0000000000000000aaaaaaaaaaaaaaaa'))
            cli_main()
        self.assertMultiLineEqual(capture.getvalue(), """\
Upgrade path is 1600
Target phase: 80%
""")


class TestCLIDuplicateDestinations(ServerTestBase):
    INDEX_FILE = 'main.index_04.json'
    CHANNEL_FILE = 'main.channels_03.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_duplicate_destinations(self, config_d):
        # main.index_04.json has the bug we saw in the wild in LP: #1250181.
        # There, the server erroneously included a data file twice in two
        # different images.  This can't happen and indicates a server
        # problem.  The client must refuse to upgrade in this case, by raising
        # an exception.
        self._setup_server_keyrings()
        with ExitStack() as resources:
            resources.enter_context(argv('-C', config_d))
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
    INDEX_FILE = 'main.index_05.json'
    CHANNEL_FILE = 'main.channels_02.json'
    CHANNEL = 'daily'
    DEVICE = 'manta'

    @configuration
    def test_no_apply(self, config_d):
        # `system-image-cli --no-apply` downloads everything but does not
        # apply the update.
        self._setup_server_keyrings()
        capture = StringIO()
        self._resources.enter_context(capture_print(capture))
        self._resources.enter_context(
            argv('-C', config_d, '--no-apply', '-b', 0, '-c', 'daily'))
        mock = self._resources.enter_context(
            patch('systemimage.apply.Reboot.apply'))
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
    def test_no_reboot(self, config_d):
        # `system-image-cli --no-reboot` downloads everything but does not
        # apply the update.  THIS IS DEPRECATED IN SI 3.0.
        self._setup_server_keyrings()
        capture = StringIO()
        self._resources.enter_context(capture_print(capture))
        self._resources.enter_context(
            argv('-C', config_d, '--no-reboot', '-b', 0, '-c', 'daily'))
        mock = self._resources.enter_context(
            patch('systemimage.apply.Reboot.apply'))
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
        self._resources.enter_context(capture_print(capture))
        self._resources.enter_context(
            argv('-C', config_d, '-g', '-b', 0, '-c', 'daily'))
        mock = self._resources.enter_context(
            patch('systemimage.apply.Reboot.apply'))
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
        self._resources.enter_context(capture_print(capture))
        mock = self._resources.enter_context(
            patch('systemimage.apply.Reboot.apply'))
        self._resources.enter_context(
            argv('-C', config_d, '-g', '-b', 0, '-c', 'daily'))
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
        # Run main again without the -g flag this time we reboot.
        with ExitStack() as stack:
            stack.enter_context(argv('-C', config_d, '-b', 0, '-c', 'daily'))
            stack.enter_context(
                patch('systemimage.device.check_output', return_value='manta'))
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
            resources.enter_context(capture_print(capture))
            mock = resources.enter_context(
                patch('systemimage.apply.Reboot.apply'))
            resources.enter_context(argv('-C', config_d, '--factory-reset'))
            cli_main()
        # A reboot was issued.
        self.assertTrue(mock.called)
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, dedent("""\
            format data
            """))


class TestCLIProductionReset(unittest.TestCase):
    """Test the --production-reset option for production factory resets."""

    @configuration
    def test_production_reset(self, config_d):
        # system-image-cli --production-reset
        capture = StringIO()
        with ExitStack() as resources:
            resources.enter_context(capture_print(capture))
            mock = resources.enter_context(
                patch('systemimage.apply.Reboot.apply'))
            resources.enter_context(argv('-C', config_d, '--production-reset'))
            cli_main()
        # A reboot was issued.
        self.assertTrue(mock.called)
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, dedent("""\
            format data
            enable factory_wipe
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
            self._resources.enter_context(capture_print(self._stdout))
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
        self._resources.enter_context(argv('-C', config_d, '--show-settings'))
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
        self._resources.enter_context(argv('-C', config_d, '--get', 'ant'))
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
            argv('-C', config_d, '--get', 's', '--get', 'u', '--get', 't'))
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
            argv('-C', config_d, '--get', 'missing', '--get', 'auto_download'))
        cli_main()
        # This produces a blank line, since `missing` returns the empty
        # string.  For better readability, don't indent the results.
        self.assertMultiLineEqual(self._stdout.getvalue(), """\

1
""")

    @configuration
    def test_set_key(self, config_d):
        # `system-image-cli --set key=value` sets a key/value pair.
        self._resources.enter_context(argv('-C', config_d, '--set', 'bass=4'))
        cli_main()
        self.assertEqual(Settings().get('bass'), '4')

    @configuration
    def test_change_key(self, config_d):
        # `--set key=value` changes an existing key's value.
        settings = Settings()
        settings.set('a', 'ant')
        settings.set('b', 'bee')
        settings.set('c', 'cat')
        self._resources.enter_context(argv('-C', config_d, '--set', 'b=bat'))
        cli_main()
        self.assertEqual(settings.get('a'), 'ant')
        self.assertEqual(settings.get('b'), 'bat')
        self.assertEqual(settings.get('c'), 'cat')

    @configuration
    def test_set_keys(self, config_d):
        # `--set key=value` can be used multiple times.
        self._resources.enter_context(
            argv('-C', config_d,
                 '--set', 'a=ant',
                 '--set', 'b=bee',
                 '--set', 'c=cat'))
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
        self._resources.enter_context(argv('-C', config_d, '--del', 'bee'))
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
            argv('-C', config_d, '--del', 'bee', '--del', 'cat'))
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
        self._resources.enter_context(argv('-C', config_d, '--del', 'missing'))
        cli_main()
        self.assertEqual(Settings().get('missing'), '')

    @configuration
    def test_mix_and_match(self, config_d):
        # Because argument order is not preserved, and any semantics for
        # mixing and matching database arguments would be arbitrary, it is not
        # allowed to mix them.
        capture = StringIO()
        self._resources.enter_context(capture_print(capture))
        self._resources.enter_context(
            argv('-C', config_d,
                 '--set', 'c=cat', '--del', 'bee', '--get', 'dog'))
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
            config_d = SystemImagePlugin.controller.ini_path
            override = os.path.join(config_d, '06_override.ini')
            self._stack.callback(safe_remove, override)
            with open(override, 'w', encoding='utf-8') as fp:
                print('[dbus]\nlifetime: 3s\n', file=fp)
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
        return iface.Information()

    def test_service_exits(self):
        # The dbus service automatically exits after a set amount of time.
        config_d = SystemImagePlugin.controller.ini_path
        # Nothing has been spawned yet.
        self.assertIsNone(find_dbus_process(config_d))
        self._activate()
        process = find_dbus_process(config_d)
        self.assertTrue(process.is_running())
        # Now wait for the process to self-terminate.  If this times out
        # before the process exits, a TimeoutExpired exception will be
        # raised.  Let this propagate up as a test failure.
        process.wait(timeout=6)
        self.assertFalse(process.is_running())

    def test_service_keepalive(self):
        # Proactively calling methods on the service keeps it alive.
        config_d = SystemImagePlugin.controller.ini_path
        self.assertIsNone(find_dbus_process(config_d))
        self._activate()
        process = find_dbus_process(config_d)
        self.assertTrue(process.is_running())
        # Normally the process would exit after 3 seconds, but we'll keep it
        # alive for a bit.
        for i in range(3):
            self._activate()
            time.sleep(2)
        self.assertTrue(process.is_running())

    def test_config_override(self):
        # Other ini files can override the build number and channel.
        config_d = SystemImagePlugin.controller.ini_path
        copy('main.config_07.ini', config_d, '07_override.ini')
        info = self._activate()
        # The build number.
        self.assertEqual(info['current_build_number'], '33')
        # The channel
        self.assertEqual(info['channel_name'], 'saucy')

    def test_temp_directory(self):
        # The temporary directory gets created if it doesn't exist.
        config_d = SystemImagePlugin.controller.ini_path
        config = Configuration(config_d)
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
        config = Configuration(SystemImagePlugin.controller.ini_path)
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
        config_d = SystemImagePlugin.controller.ini_path
        self.assertIsNone(find_dbus_process(config_d))
        self._activate()
        proc = find_dbus_process(config_d)
        # Attempt to start a second process on the same system bus.
        env = dict(
            DBUS_SYSTEM_BUS_ADDRESS=os.environ['DBUS_SYSTEM_BUS_ADDRESS'])
        coverage_env = os.environ.get('COVERAGE_PROCESS_START')
        if coverage_env is not None:
            env['COVERAGE_PROCESS_START'] = coverage_env
        args = (sys.executable, '-m', 'systemimage.testing.service',
                '-C', config_d)
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


class TestDBusMainNoConfigD(unittest.TestCase):
    def test_start_with_missing_config_d(self):
        # Trying to start the D-Bus service with a configuration directory
        # that doesn't exist yields an error.
        #
        # First stop any existing D-Bus service, but it's okay if it's not
        # running.
        bus = dbus.SystemBus()
        service = bus.get_object('com.canonical.SystemImage', '/Service')
        iface = dbus.Interface(service, 'com.canonical.SystemImage')
        try:
            iface.Exit()
            wait_for_service(reload=False)
        except DBusException:
            pass
        # Try to start a new process with a bogus configuration directory.
        env = dict(
            DBUS_SYSTEM_BUS_ADDRESS=os.environ['DBUS_SYSTEM_BUS_ADDRESS'])
        coverage_env = os.environ.get('COVERAGE_PROCESS_START')
        if coverage_env is not None:
            env['COVERAGE_PROCESS_START'] = coverage_env
        args = (sys.executable, '-m', 'systemimage.testing.service',
                '-C', '/does/not/exist')
        with temporary_directory() as tempdir:
            stdout_path = os.path.join(tempdir, 'stdout')
            stderr_path = os.path.join(tempdir, 'stderr')
            with ExitStack() as files:
                tempdir = files.enter_context(temporary_directory())
                stdout = files.enter_context(
                    open(stdout_path, 'w', encoding='utf-8'))
                stderr = files.enter_context(
                    open(stderr_path, 'w', encoding='utf-8'))
                try:
                    subprocess.check_call(args,
                                          universal_newlines=True, env=env,
                                          stdout=stdout, stderr=stderr)
                except subprocess.CalledProcessError as error:
                    self.assertNotEqual(error.returncode, 0)
            with open(stdout_path, 'r', encoding='utf-8') as fp:
                stdout = fp.read()
            with open(stderr_path, 'r', encoding='utf-8') as fp:
                stderr = fp.readlines()
            self.assertEqual(stdout, '')
            self.assertEqual(
                stderr[-1],
                'Configuration directory not found: .load() requires a '
                'directory: /does/not/exist\n')


class TestCLISignatures(ServerTestBase):
    INDEX_FILE = 'main.index_01.json'
    CHANNEL_FILE = 'main.channels_01.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_update_attempt_with_bad_signatures(self, config_d):
        # Let's say the index.json file has a bad signature.  The update
        # should refuse to apply.
        self._setup_server_keyrings()
        # Sign the index.json file with the wrong (i.e. bad) key.
        index_path = os.path.join(
            self._serverdir, self.CHANNEL, self.DEVICE, 'index.json')
        sign(index_path, 'spare.gpg')
        stdout = StringIO()
        with ExitStack() as resources:
            resources.enter_context(capture_print(stdout))
            # Patch argparse's stderr to capture its error messages.
            resources.push(machine_id('feedfacebeefbacafeedfacebeefbaca'))
            resources.enter_context(argv('-C', config_d, '--dry-run'))
            # Now that the index.json on the server is signed with the wrong
            # keyring, try to upgrade.
            code = cli_main()
        # The upgrade failed because of the signature.
        self.assertEqual(code, 1)
        with open(config.system.logfile, encoding='utf-8') as fp:
            logged = fp.readlines()
        # Slog through the log output and look for evidence that the upgrade
        # failed because of the faulty signature on the index.json file.
        # Then assert on those clues, but get rid of the trailing newlines.
        exception_found = False
        data_path = sig_path = None
        i = 0
        while i < len(logged):
            line = logged[i][:-1]
            i += 1
            if line.startswith('systemimage.gpg.SignatureError'):
                # There should only be one of these lines.
                self.assertFalse(exception_found)
                exception_found = True
            elif line.strip().startswith('sig path'):
                sig_path = logged[i][:-1]
                i += 1
            elif line.strip().startswith('data path'):
                data_path = logged[i][:-1]
                i += 1
        # Check the clues.
        self.assertTrue(exception_found)
        self.assertTrue(sig_path.endswith('index.json.asc'), repr(sig_path))
        self.assertTrue(data_path.endswith('index.json'), repr(data_path))

    @configuration
    def test_update_attempt_with_bad_signatures_overridden(self, config_d):
        # Let's say the index.json file has a bad signature.  Normally, the
        # update should refuse to apply, but we override the GPG checks so it
        # will succeed.
        self._setup_server_keyrings()
        # Sign the index.json file with the wrong (i.e. bad) key.
        index_path = os.path.join(
            self._serverdir, self.CHANNEL, self.DEVICE, 'index.json')
        sign(index_path, 'spare.gpg')
        stdout = StringIO()
        stderr = StringIO()
        with ExitStack() as resources:
            resources.enter_context(capture_print(stdout))
            resources.enter_context(
                patch('systemimage.main.sys.stderr', stderr))
            # Patch argparse's stderr to capture its error messages.
            resources.push(machine_id('feedfacebeefbacafeedfacebeefbaca'))
            resources.enter_context(
                argv('-C', config_d, '--dry-run', '--skip-gpg-verification'))
            # Now that the index.json on the server is signed with the wrong
            # keyring, try to upgrade.
            code = cli_main()
        # The upgrade failed because of the signature.
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), """\
Upgrade path is 1200:1201:1304
Target phase: 64%
""")
        # And we get the scary warning on the console.
        self.assertMultiLineEqual(stderr.getvalue(), """\
WARNING: All GPG signature verifications have been disabled.
Your upgrades are INSECURE.
""")


class TestCLIProgress(ServerTestBase):
    INDEX_FILE = 'main.index_01.json'
    CHANNEL_FILE = 'main.channels_01.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_dots_progress(self, config_d):
        # --progress=dots prints a bunch of dots to stderr.
        self._setup_server_keyrings()
        stderr = StringIO()
        with ExitStack() as resources:
            resources.enter_context(
                patch('systemimage.main.LINE_LENGTH', 10))
            resources.enter_context(
                patch('systemimage.main.sys.stderr', stderr))
            resources.enter_context(
                argv('-C', config_d, '-b', '0', '--no-reboot',
                     '--progress', 'dots'))
            cli_main()
        # There should be some dots in the stderr.
        self.assertGreater(stderr.getvalue().count('.'), 2)

    @configuration
    def test_json_progress(self, config_d):
        # --progress=json prints some JSON to stdout.
        self._setup_server_keyrings()
        stdout = StringIO()
        with ExitStack() as resources:
            resources.enter_context(
                patch('systemimage.main.sys.stdout', stdout))
            resources.enter_context(
                argv('-C', config_d, '-b', '0', '--no-reboot',
                     '--progress', 'json'))
            cli_main()
        # stdout is now filled with JSON goodness.  We can't assert too much
        # about the contents though.
        line_count = 0
        for line in stdout.getvalue().splitlines():
            line_count += 1
            record = json.loads(line)
            self.assertEqual(record['type'], 'progress')
            self.assertIn('now', record)
            self.assertIn('total', record)
        self.assertGreater(line_count, 4)

    @configuration
    def test_logfile_progress(self, config_d):
        # --progress=logfile dumps some messages to the log file.
        self._setup_server_keyrings()
        log_mock = MagicMock()
        from systemimage.main import _LogfileProgress
        class Testable(_LogfileProgress):
            def __init__(self, log):
                super().__init__(log)
                self._log = log_mock
        with ExitStack() as resources:
            resources.enter_context(
                patch('systemimage.main._LogfileProgress', Testable))
            resources.enter_context(
                argv('-C', config_d, '-b', '0', '--no-reboot',
                     '--progress', 'logfile'))
            cli_main()
        self.assertGreater(log_mock.debug.call_count, 4)
        positional, keyword = log_mock.debug.call_args
        self.assertTrue(positional[0].startswith('received: '))

    @configuration
    def test_all_progress(self, config_d):
        # We can have more than one --progress flag.
        self._setup_server_keyrings()
        stdout = StringIO()
        stderr = StringIO()
        log_mock = MagicMock()
        from systemimage.main import _LogfileProgress
        class Testable(_LogfileProgress):
            def __init__(self, log):
                super().__init__(log)
                self._log = log_mock
        with ExitStack() as resources:
            resources.enter_context(
                patch('systemimage.main.LINE_LENGTH', 10))
            resources.enter_context(
                patch('systemimage.main.sys.stderr', stderr))
            resources.enter_context(
                patch('systemimage.main.sys.stdout', stdout))
            resources.enter_context(
                patch('systemimage.main._LogfileProgress', Testable))
            resources.enter_context(
                argv('-C', config_d, '-b', '0', '--no-reboot',
                     '--progress', 'dots',
                     '--progress', 'json',
                     '--progress', 'logfile'))
            cli_main()
        self.assertGreater(stderr.getvalue().count('.'), 2)
        line_count = 0
        for line in stdout.getvalue().splitlines():
            line_count += 1
            record = json.loads(line)
            self.assertEqual(record['type'], 'progress')
            self.assertIn('now', record)
            self.assertIn('total', record)
        self.assertGreater(line_count, 4)
        self.assertGreater(log_mock.debug.call_count, 4)
        positional, keyword = log_mock.debug.call_args
        self.assertTrue(positional[0].startswith('received: '))

    @configuration
    def test_bad_progress(self, config_d):
        # An unknown progress type results in an error.
        stderr = StringIO()
        with ExitStack() as resources:
            resources.enter_context(
                patch('systemimage.main.sys.stderr', stderr))
            resources.enter_context(
                argv('-C', config_d, '-b', '0', '--no-reboot',
                     '--progress', 'not-a-meter'))
            with self.assertRaises(SystemExit) as cm:
                cli_main()
            exit_code = cm.exception.code
        self.assertEqual(exit_code, 2)
        self.assertEqual(
            stderr.getvalue().splitlines()[-1],
            'system-image-cli: error: Unknown progress meter: not-a-meter')
