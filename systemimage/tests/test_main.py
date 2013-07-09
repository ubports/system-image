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

import os
import shutil
import unittest

from contextlib import ExitStack
from io import StringIO
from pkg_resources import resource_filename
from systemimage.config import config
from systemimage.main import main
from systemimage.tests.helpers import temporary_directory, test_data_path
from unittest.mock import patch


class TestMain(unittest.TestCase):
    maxDiff = None

    def test_config_file_good_path(self):
        # The default configuration file exists.
        with ExitStack() as stack:
            # Ignore printed output.
            stack.enter_context(patch('builtins.print'))
            # Patch arguments to something harmless.
            stack.enter_context(
                patch('systemimage.main.sys.argv', ['--build']))
            # Patch default configuration file.
            tempdir = stack.enter_context(temporary_directory())
            ini_path = os.path.join(tempdir, 'client.ini')
            shutil.copy(
                resource_filename('systemimage.data', 'client.ini'), tempdir)
            stack.enter_context(
                patch('systemimage.main.DEFAULT_CONFIG_FILE', ini_path))
            main()
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
            stack.enter_context(patch('systemimage.main.sys.argv', []))
            # Patch default configuration file.
            stack.enter_context(
                patch('systemimage.main.DEFAULT_CONFIG_FILE',
                      '/does/not/exist/client.ini'))
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 2)
            self.assertEqual(stderr.getvalue(), """\
usage: system-image-cli [-h] [--version] [-C CONFIG] [-b] [-u UPGRADE] [-v]
system-image-cli: error:\x20
Configuration file not found: /does/not/exist/client.ini
""")

    def test_missing_explicit_config_file(self):
        # An explicit configuration file given with -C is missing.
        with ExitStack() as stack:
            # Capture sys.stderr messages.
            stderr = StringIO()
            stack.enter_context(patch('argparse._sys.stderr', stderr))
            # Patch arguments.
            stack.enter_context(
                patch('systemimage.main.sys.argv',
                      ['-C', '/does/not/exist.ini']))
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 2)
            self.assertEqual(stderr.getvalue(), """\
usage: system-image-cli [-h] [--version] [-C CONFIG] [-b] [-u UPGRADE] [-v]
system-image-cli: error:\x20
Configuration file not found: /does/not/exist.ini
""")

    def test_ensure_directories_exist(self):
        # The temporary and var directories are created if they don't exist.
        with ExitStack() as stack:
            dir_1 = stack.enter_context(temporary_directory())
            dir_2 = stack.enter_context(temporary_directory())
            # Create a configuration file with directories that point to
            # non-existent locations.
            config_ini = os.path.join(dir_1, 'client.ini')
            with open(test_data_path('config_00.ini'), encoding='utf-8') as fp:
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
                'systemimage.main.sys.argv', ['-C', config_ini, '--build']))
            main()
            keyring_dir = os.path.dirname(config.gpg.image_master)
            systemp_dir = config.system.tempdir
            self.assertTrue(os.path.exists(keyring_dir))
            self.assertTrue(os.path.exists(systemp_dir))
