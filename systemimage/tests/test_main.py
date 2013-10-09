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

"""Test the main entry point."""

__all__ = [
    'TestCLIMain',
    'TestCLIMainDryRun',
    'TestDBusMain',
    ]


import os
import dbus
import stat
import psutil
import shutil
import unittest

from contextlib import ExitStack
from datetime import datetime
from functools import partial
from io import StringIO
from pkg_resources import resource_filename, resource_string as resource_bytes
from systemimage.config import Configuration, config
from systemimage.main import main as cli_main
from systemimage.testing.helpers import (
    configuration, copy, data_path, temporary_directory, touch_build)
from systemimage.testing.nose import SystemImagePlugin
# This should be moved and refactored.
from systemimage.tests.test_state import _StateTestsBase
from textwrap import dedent
from unittest.mock import MagicMock, patch


SPACE = ' '
TIMESTAMP = datetime(2013, 8, 1, 12, 11, 10).timestamp()


def _find_dbus_proc(ini_path):
    # This method searches all processes for the one matching the
    # system-image-dbus service.  This is harder than it should be because
    # while dbus-launch gives us the PID of the dbus-launch process itself,
    # that can't be used to find the appropriate child process, because
    # D-Bus activated processes are orphaned to init as their parent.
    #
    # This then does a brute-force search over all the processes, looking one
    # that has a particular command line indicating that it's the
    # system-image-dbus service.  We don't run this latter by that name
    # though, since that's a wrapper created by setup.py's entry points.
    #
    # To make doubly certain we're not going to get the wrong process (in case
    # there are multiple system-image-dbus processes running), we'll also look
    # for the specific ini_path for the instance we care about.  Yeah, this
    # all kind of sucks, but should be effective in finding the one we need to
    # track.
    for process in psutil.process_iter():
        cmdline = SPACE.join(process.cmdline)
        if 'systemimage.service' in cmdline and ini_path in cmdline:
            return process
    return None


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
        with open(data_path('config_00.ini'), encoding='utf-8') as fp:
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
        config = Configuration()
        config.load(config_ini)
        self.assertFalse(os.path.exists(config.system.tempdir))
        self.assertFalse(os.path.exists(config.system.logfile))
        self._resources.enter_context(patch(
            'systemimage.main.sys.argv',
            ['argv0', '-C', config_ini, '--info']))
        cli_main()
        mode = os.stat(config.system.tempdir).st_mode
        self.assertEqual(stat.filemode(mode), 'drwx------')
        mode = os.stat(os.path.dirname(config.system.logfile)).st_mode
        self.assertEqual(stat.filemode(mode), 'drwx------')
        mode = os.stat(config.system.logfile).st_mode
        self.assertEqual(stat.filemode(mode), '-rw-------')

    @configuration
    def test_info(self, ini_file):
        # -i/--info gives information about the device, including the current
        # build number, channel, and device name.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file, '--info']))
        # Set up the build number.
        config = Configuration()
        config.load(ini_file)
        touch_build(20130701, TIMESTAMP)
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20130701
            device name: nexus7
            channel: stable
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_info_last_update_channel_ini(self, ini_file):
        # --info's last update date uses the mtime of channel.ini even when
        # /etc/ubuntu-build exists.
        channel_ini = os.path.join(os.path.dirname(ini_file), 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_01.ini', head, tail)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file, '--info']))
        # Set up the build number.
        config = Configuration()
        config.load(ini_file)
        touch_build(20130701)
        timestamp_1 = int(datetime(2011, 1, 8, 2, 3, 4).timestamp())
        os.utime(config.system.build_file, (timestamp_1, timestamp_1))
        timestamp_2 = int(datetime(2011, 8, 1, 5, 6, 7).timestamp())
        os.utime(channel_ini, (timestamp_2, timestamp_2))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20130833
            device name: nexus7
            channel: proposed
            last update: 2011-08-01 05:06:07
            """))

    @configuration
    def test_info_last_update_date_fallback(self, ini_file):
        # --info's last update date falls back to the mtime of
        # /etc/ubuntu-build when no channel.ini file exists.
        channel_ini = os.path.join(os.path.dirname(ini_file), 'channel.ini')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file, '--info']))
        # Set up the build number.
        config = Configuration()
        config.load(ini_file)
        touch_build(20130701)
        timestamp_1 = int(datetime(2011, 1, 8, 2, 3, 4).timestamp())
        os.utime(config.system.build_file, (timestamp_1, timestamp_1))
        self.assertFalse(os.path.exists(channel_ini))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20130701
            device name: nexus7
            channel: stable
            last update: 2011-01-08 02:03:04
            """))

    @configuration
    def test_build_number(self, ini_file):
        # -b/--build overrides the build number.
        config = Configuration()
        config.load(ini_file)
        touch_build(20130701, TIMESTAMP)
        # Use --build to override the default build number.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file,
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
    def test_device_name(self, ini_file):
        # -d/--device overrides the device type.
        config = Configuration()
        config.load(ini_file)
        touch_build(20130701, TIMESTAMP)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file,
                   '--device', 'phablet',
                   '--info']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20130701
            device name: phablet
            channel: stable
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_channel_name(self, ini_file):
        # -c/--channel overrides the channel.
        config = Configuration()
        config.load(ini_file)
        touch_build(20130701, TIMESTAMP)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file,
                   '--channel', 'daily-proposed',
                   '--info']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20130701
            device name: nexus7
            channel: daily-proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_all_overrides(self, ini_file):
        # Use -b -d and -c together.
        config = Configuration()
        config.load(ini_file)
        touch_build(20130701, TIMESTAMP)
        # Use --build to override the default build number.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file,
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
    def test_bad_build_number_override(self, ini_file):
        # -b/--build requires an integer.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file, '--build', 'bogus']))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
          self._stderr.getvalue().splitlines()[-1],
          'system-image-cli: error: -b/--build requires an integer: bogus')

    @configuration
    def test_channel_ini_override_build_number(self, ini_file):
        # The channel.ini file can override the build number.
        copy('channel_01.ini', os.path.dirname(ini_file), 'channel.ini')
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file, '-i']))
        # Set up the build number.
        config = Configuration()
        config.load(ini_file)
        touch_build(20130701, TIMESTAMP)
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20130833
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_channel_ini_override_channel(self, ini_file):
        # The channel.ini file can override the channel.
        channel_ini = os.path.join(os.path.dirname(ini_file), 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_01.ini', head, tail)
        os.utime(channel_ini, (TIMESTAMP, TIMESTAMP))
        config = Configuration()
        config.load(ini_file)
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file, '-i']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20130833
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            """))

    @configuration
    def test_log_file(self, ini_file):
        # Test that the system log file gets created and written.
        config = Configuration()
        config.load(ini_file)
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
            ['argv0', '-C', ini_file]))
        self._resources.enter_context(
            patch('systemimage.main.State', FakeState))
        cli_main()
        self.assertTrue(os.path.exists(config.system.logfile))
        with open(config.system.logfile, encoding='utf-8') as fp:
            logged = fp.read()
        # Ignore any leading timestamp and the trailing newline.
        self.assertEqual(logged[-38:-1],
                         'running state machine [stable/nexus7]')

    @configuration
    def test_bad_filter_type(self, ini_file):
        # --filter option where value is not `full` or `delta` is an error.
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file, '--filter', 'bogus']))
        with self.assertRaises(SystemExit) as cm:
            cli_main()
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(
            self._stderr.getvalue().splitlines()[-1],
            'system-image-cli: error: Bad filter type: bogus')

    @configuration
    def test_version_detail(self, ini_file):
        # --info where channel.ini has [service]version_detail
        channel_ini = os.path.join(os.path.dirname(ini_file), 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_03.ini', head, tail)
        os.utime(channel_ini, (TIMESTAMP, TIMESTAMP))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file, '-i']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20130833
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            version ubuntu: 123
            version mako: 456
            version custom: 789
            """))

    @configuration
    def test_no_version_detail(self, ini_file):
        # --info where channel.ini does not hav [service]version_detail
        channel_ini = os.path.join(os.path.dirname(ini_file), 'channel.ini')
        head, tail = os.path.split(channel_ini)
        copy('channel_01.ini', head, tail)
        os.utime(channel_ini, (TIMESTAMP, TIMESTAMP))
        self._resources.enter_context(
            patch('systemimage.main.sys.argv',
                  ['argv0', '-C', ini_file, '-i']))
        cli_main()
        self.assertEqual(self._stdout.getvalue(), dedent("""\
            current build number: 20130833
            device name: nexus7
            channel: proposed
            last update: 2013-08-01 12:11:10
            """))


class TestCLIMainDryRun(_StateTestsBase):
    INDEX_FILE = 'index_14.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_dry_run(self, ini_file):
        # `system-image-cli --dry-run` prints the winning upgrade path.
        self._setup_keyrings()
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            capture = StringIO()
            stack.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', ini_file, '--dry-run']))
            cli_main()
            self.assertEqual(capture.getvalue(),
                             'Upgrade path is 20130200:20130201:20130304\n')

    @configuration
    def test_dry_run_no_update(self, ini_file):
        # `system-image-cli --dry-run` when there are no updates available.
        self._setup_keyrings()
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            capture = StringIO()
            stack.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', ini_file, '--dry-run']))
            # Set up the build number.
            config = Configuration()
            config.load(ini_file)
            touch_build(20130701)
            cli_main()
            self.assertEqual(capture.getvalue(), 'Already up-to-date\n')

    @configuration
    def test_dry_run_bad_channel(self, ini_file):
        # 'system-image-cli --dry-run --channel <bad-channel>` should say it's
        # already up-to-date.
        self._setup_keyrings()
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            capture = StringIO()
            stack.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            # Use --build to override the default build number.
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', ini_file,
                       '--channel', 'daily-proposed',
                       '--dry-run']))
            cli_main()
            self.assertEqual(capture.getvalue(), 'Already up-to-date\n')


class TestCLIFilters(_StateTestsBase):
    INDEX_FILE = 'index_15.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_filter_full(self, ini_file):
        # With --filter=full, only full updates will be considered.
        self._setup_keyrings()
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            capture = StringIO()
            stack.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', ini_file, '--dry-run',
                       '--filter', 'full']))
            # Set up the build number.
            config = Configuration()
            config.load(ini_file)
            touch_build(20120100)
            cli_main()
            self.assertEqual(capture.getvalue(), 'Already up-to-date\n')

    @configuration
    def test_filter_delta(self, ini_file):
        # With --filter=delta, only delta updates will be considered.
        self._setup_keyrings()
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            capture = StringIO()
            stack.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', ini_file, '--dry-run',
                       '--filter', 'delta']))
            # Set up the build number.
            config = Configuration()
            config.load(ini_file)
            touch_build(20120100)
            cli_main()
            self.assertEqual(capture.getvalue(), 'Upgrade path is 20130600\n')


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
        self.assertIsNone(_find_dbus_proc(self.ini_path))
        self._activate()
        process = _find_dbus_proc(self.ini_path)
        self.assertTrue(process.is_running())
        # Now wait for the process to self-terminate.  If this times out
        # before the process exits, a TimeoutExpired exception will be
        # raised.  Let this propagate up as a test failure.
        process.wait(timeout=6)
        self.assertFalse(process.is_running())

    def test_channel_ini_override(self):
        # An optional channel.ini can override the build number and channel.
        #
        # The config.ini file names the `stable` channel.  Let's create an
        # ubuntu-build file with a fake version number.
        config = Configuration()
        config.load(self.ini_path)
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
        config = Configuration()
        config.load(self.ini_path)
        # Delete the temporary directory, which will have been created by the
        # .set_mode() call in the setUp().  That invokes a 'stopper' for the
        # -dbus process, which has the perverse effect of first D-Bus
        # activating the process, and thus creating the temporary directory
        # before calling .Exit().  Deleting it now will allow the .Info() call
        # below to re-active the process and thus re-create the directory.
        shutil.rmtree(config.system.tempdir)
        self.assertFalse(os.path.exists(config.system.tempdir))
        self._activate()
        self.assertTrue(os.path.exists(config.system.tempdir))

    def test_permissions(self):
        # LP: #1235975 - The created tempdir had unsafe permissions.
        config = Configuration()
        config.load(self.ini_path)
        shutil.rmtree(config.system.tempdir)
        os.remove(config.system.logfile)
        self._activate()
        mode = os.stat(config.system.tempdir).st_mode
        self.assertEqual(stat.filemode(mode), 'drwx------')
        mode = os.stat(os.path.dirname(config.system.logfile)).st_mode
        self.assertEqual(stat.filemode(mode), 'drwx------')
        mode = os.stat(config.system.logfile).st_mode
        self.assertEqual(stat.filemode(mode), '-rw-------')
