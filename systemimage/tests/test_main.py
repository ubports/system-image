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
import sys
import time
import shutil
import unittest
import subprocess

from contextlib import ExitStack
from distutils.spawn import find_executable
from functools import partial
from io import StringIO
from pkg_resources import resource_filename
from systemimage.config import Configuration, config
from systemimage.main import main as cli_main
from systemimage.testing.helpers import (
    configuration, copy, data_path, temporary_directory)
# This should be moved and refactored.
from systemimage.tests.test_state import _StateTestsBase
from unittest.mock import patch


DBUS_LAUNCH = find_executable('dbus-launch')


class TestCLIMain(unittest.TestCase):
    maxDiff = None

    def test_config_file_good_path(self):
        # The default configuration file exists.
        with ExitStack() as stack:
            # Ignore printed output.
            stack.enter_context(patch('builtins.print'))
            # Patch arguments to something harmless.
            stack.enter_context(
                patch('systemimage.main.sys.argv', ['argv0', '--build']))
            # Patch default configuration file.
            tempdir = stack.enter_context(temporary_directory())
            ini_path = os.path.join(tempdir, 'client.ini')
            shutil.copy(
                resource_filename('systemimage.data', 'client.ini'), tempdir)
            stack.enter_context(
                patch('systemimage.main.DEFAULT_CONFIG_FILE', ini_path))
            # Mock out the initialize() call so that the main() doesn't try to
            # create a log file in a non-existent system directory.
            stack.enter_context(patch('systemimage.main.initialize'))
            cli_main()
            self.assertEqual(config.config_file, ini_path)
            self.assertEqual(config.system.build_file, '/etc/ubuntu-build')

    def test_missing_default_config_file(self):
        # The default configuration file is missing.
        with ExitStack() as stack:
            # Capture sys.stderr messages.
            stderr = StringIO()
            stack.enter_context(patch('argparse._sys.stderr', stderr))
            # Patch arguments to be empty, otherwise the unittest arguments
            # will leak through.
            stack.enter_context(patch('systemimage.main.sys.argv', ['argv0']))
            # Patch default configuration file.
            stack.enter_context(
                patch('systemimage.main.DEFAULT_CONFIG_FILE',
                      '/does/not/exist/client.ini'))
            with self.assertRaises(SystemExit) as cm:
                cli_main()
            self.assertEqual(cm.exception.code, 2)
            self.assertEqual(
                stderr.getvalue().splitlines()[-1],
                'Configuration file not found: /does/not/exist/client.ini')

    def test_missing_explicit_config_file(self):
        # An explicit configuration file given with -C is missing.
        with ExitStack() as stack:
            # Capture sys.stderr messages.
            stderr = StringIO()
            stack.enter_context(patch('argparse._sys.stderr', stderr))
            # Patch arguments.
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', '/does/not/exist.ini']))
            with self.assertRaises(SystemExit) as cm:
                cli_main()
            self.assertEqual(cm.exception.code, 2)
            self.assertEqual(
                stderr.getvalue().splitlines()[-1],
                'Configuration file not found: /does/not/exist.ini')

    def test_ensure_directories_exist(self):
        # The temporary and var directories are created if they don't exist.
        with ExitStack() as stack:
            dir_1 = stack.enter_context(temporary_directory())
            dir_2 = stack.enter_context(temporary_directory())
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
            # Invoke main() in such a way that the directories will be
            # created.  We don't care about the output.
            stack.enter_context(patch('builtins.print'))
            # Patch arguments to something harmless.
            stack.enter_context(patch(
                'systemimage.main.sys.argv',
                ['argv0', '-C', config_ini, '--build']))
            self.assertFalse(os.path.exists(tmpdir))
            cli_main()
            self.assertTrue(os.path.exists(tmpdir))

    @configuration
    def test_build_number(self, ini_file):
        # -b gives the build number.
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            capture = StringIO()
            stack.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            stack.enter_context(
                patch('systemimage.main.sys.argv', ['argv0', '-b']))
            # Set up the build number.
            config = Configuration()
            config.load(ini_file)
            with open(config.system.build_file, 'w', encoding='utf-8') as fp:
                print(20130701, file=fp)
            stack.enter_context(
                patch('systemimage.main.DEFAULT_CONFIG_FILE', ini_file))
            cli_main()
            self.assertEqual(capture.getvalue(), 'build number: 20130701\n')

    @configuration
    def test_channel_ini_override_build_number(self, ini_file):
        # The channel.ini file can override the build number.
        channel_ini = os.path.join(os.path.dirname(ini_file), 'channel.ini')
        shutil.copy(
            resource_filename('systemimage.tests.data', 'channel_01.ini'),
            channel_ini)
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            capture = StringIO()
            stack.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', ini_file, '-b']))
            # Set up the build number.
            config = Configuration()
            config.load(ini_file)
            with open(config.system.build_file, 'w', encoding='utf-8') as fp:
                print(20130701, file=fp)
            cli_main()
            self.assertEqual(capture.getvalue(), 'build number: 20130833\n')

    @configuration
    def test_channel_ini_override_channel(self, ini_file):
        # The channel.ini file can override the channel.
        channel_ini = os.path.join(os.path.dirname(ini_file), 'channel.ini')
        shutil.copy(
            resource_filename('systemimage.tests.data', 'channel_01.ini'),
            channel_ini)
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            capture = StringIO()
            stack.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            config = Configuration()
            config.load(ini_file)
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', ini_file, '-c']))
            cli_main()
            self.assertEqual(capture.getvalue(),
                             'channel/device: proposed/nexus7\n')

    @configuration
    def test_channel_device(self, ini_file):
        # -c gives the channel/device name.
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            capture = StringIO()
            stack.enter_context(
                patch('builtins.print', partial(print, file=capture)))
            stack.enter_context(
                patch('systemimage.main.sys.argv', ['argv0', '-c']))
            stack.enter_context(
                patch('systemimage.device.check_output',
                      return_value='nexus7'))
            stack.enter_context(
                patch('systemimage.main.DEFAULT_CONFIG_FILE', ini_file))
            cli_main()
            self.assertEqual(capture.getvalue(),
                             'channel/device: stable/nexus7\n')

    @configuration
    def test_log_file(self, ini_file):
        # Test that the system log file gets created and written.
        config = Configuration()
        config.load(ini_file)
        self.assertFalse(os.path.exists(config.system.logfile))
        class FakeState:
            def __init__(self, candidate_filter):
                pass
            def __iter__(self):
                return self
            def __next__(self):
                raise StopIteration
        with ExitStack() as stack:
            stack.enter_context(patch('systemimage.main.sys.argv',
                                      ['argv0', '-C', ini_file]))
            stack.enter_context(patch('systemimage.main.State', FakeState))
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
        with ExitStack() as stack:
            # We patch builtin print() rather than sys.stdout because the
            # latter can mess with pdb output should we need to trace through
            # the code.
            stderr = StringIO()
            stack.enter_context(patch('argparse._sys.stderr', stderr))
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['argv0', '-C', ini_file, '--filter', 'bogus']))
            with self.assertRaises(SystemExit) as cm:
                cli_main()
            self.assertEqual(cm.exception.code, 2)
            self.assertEqual(
                stderr.getvalue().splitlines()[-1],
                'system-image-cli: error: Bad filter type: bogus')


class TestCLIMainDryRun(_StateTestsBase):
    INDEX_FILE = 'index_14.json'

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
            with open(config.system.build_file, 'w', encoding='utf-8') as fp:
                print(20130701, file=fp)
            cli_main()
            self.assertEqual(capture.getvalue(), 'Already up-to-date\n')


class TestCLIFilters(_StateTestsBase):
    INDEX_FILE = 'index_15.json'

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
            with open(config.system.build_file, 'w', encoding='utf-8') as fp:
                print(20120100, file=fp)
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
            with open(config.system.build_file, 'w', encoding='utf-8') as fp:
                print(20120100, file=fp)
            cli_main()
            self.assertEqual(capture.getvalue(), 'Upgrade path is 20130600\n')


@unittest.skip('dbus-launch only supports session bus (LP: #1206588)')
@unittest.skipUnless(DBUS_LAUNCH is not None, 'dbus-launch not found')
class TestDBusMain(unittest.TestCase):
    def test_service_exits(self):
        # The dbus service automatically exits after a set amount of time.
        with temporary_directory() as tmpdir:
            # This has a timeout of 3 seconds.
            copy('config_02.ini', tmpdir, 'client.ini')
            start = time.time()
            subprocess.check_call(
                [DBUS_LAUNCH,
                 sys.executable, '-m', 'systemimage.service', '-C',
                 os.path.join(tmpdir, 'client.ini')
                 ], timeout=6)
            end = time.time()
            self.assertLess(end - start, 6)

    @unittest.skip('XXX FIXME')
    def test_channel_ini_override(self):
        # An optional channel.ini can override the build number and channel.
        pass
