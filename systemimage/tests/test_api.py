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

"""Test the DBus API mediator."""


__all__ = [
    'TestAPI',
    'TestAPIVersionDetail',
    ]


import os

from pathlib import Path
from systemimage.api import Mediator
from systemimage.config import config
from systemimage.download import Canceled
from systemimage.testing.helpers import (
    ServerTestBase, chmod, configuration, copy, setup_index, sign,
    touch_build)
from textwrap import dedent
from unittest.mock import patch


class TestAPI(ServerTestBase):
    INDEX_FILE = 'api.index_01.json'
    CHANNEL_FILE = 'api.channels_01.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_update_available(self):
        # Because our build number is lower than the latest available in the
        # index file, there is an update available.
        self._setup_server_keyrings()
        update = Mediator().check_for_update()
        self.assertTrue(update.is_available)

    @configuration
    def test_update_available_cached(self):
        # If we try to check twice on the same mediator object, the second one
        # will return the cached update.
        self._setup_server_keyrings()
        mediator = Mediator()
        update_1 = mediator.check_for_update()
        self.assertTrue(update_1.is_available)
        update_2 = mediator.check_for_update()
        self.assertTrue(update_2.is_available)
        self.assertIs(update_1, update_2)

    @configuration
    def test_update_available_version(self):
        # An update is available.  What's the target version number?
        self._setup_server_keyrings()
        update = Mediator().check_for_update()
        self.assertEqual(update.version, '1600')

    @configuration
    def test_no_update_available_version(self):
        # No update is available, so the target version number is zero.
        self._setup_server_keyrings()
        touch_build(1600)
        update = Mediator().check_for_update()
        self.assertFalse(update.is_available)
        self.assertEqual(update.version, '')

    @configuration
    def test_no_update_available_at_latest(self):
        # Because our build number is equal to the latest available in the
        # index file, there is no update available.
        self._setup_server_keyrings()
        touch_build(1600)
        update = Mediator().check_for_update()
        self.assertFalse(update.is_available)

    @configuration
    def test_no_update_available_newer(self):
        # Because our build number is higher than the latest available in the
        # index file, there is no update available.
        self._setup_server_keyrings()
        touch_build(1700)
        update = Mediator().check_for_update()
        self.assertFalse(update.is_available)

    @configuration
    def test_get_details(self):
        # Get the details of an available update.
        self._setup_server_keyrings()
        # Index 14 has a more interesting upgrade path, and will yield a
        # richer description set.
        index_dir = Path(self._serverdir) / self.CHANNEL / self.DEVICE
        index_path = index_dir / 'index.json'
        copy('api.index_02.json', index_dir, 'index.json')
        sign(index_path, 'device-signing.gpg')
        setup_index('api.index_02.json', self._serverdir, 'device-signing.gpg')
        # Get the descriptions.
        update = Mediator().check_for_update()
        self.assertTrue(update.is_available)
        self.assertEqual(update.size, 180009)
        self.assertEqual(len(update.descriptions), 3)
        # The first contains the descriptions for the full update.
        self.assertEqual(update.descriptions[0], {
            'description': 'Full B',
            'description-en': 'The full B',
            })
        # The first delta.
        self.assertEqual(update.descriptions[1], {
            'description': 'Delta B.1',
            'description-en_US': 'This is the delta B.1',
            'description-xx': 'XX This is the delta B.1',
            'description-yy': 'YY This is the delta B.1',
            'description-yy_ZZ': 'YY-ZZ This is the delta B.1',
            })
        # The second delta.
        self.assertEqual(update.descriptions[2], {
            'description': 'Delta B.2',
            'description-xx': 'Oh delta, my delta',
            'description-xx_CC': 'This hyar is the delta B.2',
            })

    @configuration
    def test_download(self):
        # After checking that an update is available, complete the update, but
        # don't reboot.
        self._setup_server_keyrings()
        mediator = Mediator()
        self.assertTrue(mediator.check_for_update())
        # Make sure a reboot did not get issued.
        with patch('systemimage.apply.Reboot.apply') as mock:
            mediator.download()
        # The update was not applied.
        self.assertFalse(mock.called)
        # But the command file did get written, and all the files are present.
        path = Path(config.updater.cache_partition) / 'ubuntu_command'
        with path.open('r', encoding='utf-8') as fp:
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
        # And the blacklist keyring is available too.
        self.assertEqual(set(os.listdir(config.updater.data_partition)), set([
            'blacklist.tar.xz',
            'blacklist.tar.xz.asc',
            ]))

    @configuration
    def test_apply(self):
        # Run the intermediate steps, applying the update at the end.
        self._setup_server_keyrings()
        mediator = Mediator()
        # Mock to check the state of reboot.
        with patch('systemimage.apply.Reboot.apply') as mock:
            mediator.check_for_update()
            mediator.download()
            self.assertFalse(mock.called)
            mediator.apply()
            self.assertTrue(mock.called)

    @configuration
    def test_factory_reset(self):
        mediator = Mediator()
        with patch('systemimage.apply.Reboot.apply') as mock:
            mediator.factory_reset()
        self.assertTrue(mock.called)
        path = Path(config.updater.cache_partition) / 'ubuntu_command'
        with path.open('r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, dedent("""\
            format data
            """))

    @configuration
    def test_production_reset(self):
        mediator = Mediator()
        with patch('systemimage.apply.Reboot.apply') as mock:
            mediator.production_reset()
        self.assertTrue(mock.called)
        path = Path(config.updater.cache_partition) / 'ubuntu_command'
        with path.open('r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, dedent("""\
            format data
            enable factory_wipe
            """))

    @configuration
    def test_cancel(self):
        # When we get to the step of downloading the files, cancel it.
        self._setup_server_keyrings()
        mediator = Mediator()
        mediator.check_for_update()
        mediator.cancel()
        self.assertRaises(Canceled, mediator.download)

    @configuration
    def test_callback(self):
        # When downloading, we get callbacks.
        self._setup_server_keyrings()
        received_bytes = 0
        total_bytes = 0
        def callback(received, total):
            nonlocal received_bytes, total_bytes
            received_bytes = received
            total_bytes = total
        mediator = Mediator(callback)
        mediator.check_for_update()
        # Checking for updates does not trigger the callback.
        self.assertEqual(received_bytes, 0)
        self.assertEqual(total_bytes, 0)
        mediator.download()
        # We don't know exactly how many bytes got downloaded, but we know
        # some did.
        self.assertNotEqual(received_bytes, 0)
        self.assertNotEqual(total_bytes, 0)

    from unittest import skipUnless
    from systemimage.testing.controller import USING_PYCURL

    @skipUnless(USING_PYCURL, 'LP: #1411866')
    @configuration
    def test_state_machine_exceptions(self, config):
        # An exception in the state machine captures the exception and returns
        # an error string in the Update instance.
        self._setup_server_keyrings()
        with chmod(config.updater.cache_partition, 0):
            update = Mediator().check_for_update()
        # There's no winning path, but there is an error.
        self.assertFalse(update.is_available)
        self.assertIn('Permission denied', update.error)


class TestAPIVersionDetail(ServerTestBase):
    INDEX_FILE = 'api.index_03.json'
    CHANNEL_FILE = 'api.channels_01.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_update_available_version(self):
        # An update is available.  What's the target version number?
        self._setup_server_keyrings()
        update = Mediator().check_for_update()
        self.assertEqual(update.version_detail,
                         'ubuntu=101,raw-device=201,version=301')

    @configuration
    def test_no_update_available_version(self):
        # No update is available, so the target version number is zero.
        self._setup_server_keyrings()
        touch_build(1600)
        update = Mediator().check_for_update()
        self.assertFalse(update.is_available)
        self.assertEqual(update.version_detail, '')
