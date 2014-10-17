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

"""Test the DBus API mediator."""


__all__ = [
    'TestAPI',
    ]


import os
import json
import unittest

from contextlib import ExitStack
from datetime import datetime, timedelta
from gi.repository import GLib
from hashlib import sha256
from systemimage.api import Mediator
from systemimage.config import Configuration, config
from systemimage.download import Canceled
from systemimage.gpg import SignatureError
from systemimage.helpers import MiB
from systemimage.testing.helpers import (
    ServerTestBase, chmod, configuration, copy, setup_index, sign,
    touch_build)
from textwrap import dedent
from unittest.mock import patch


class TestAPI(ServerTestBase):
    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_06.json'
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
        index_dir = os.path.join(self._serverdir, self.CHANNEL, self.DEVICE)
        index_path = os.path.join(index_dir, 'index.json')
        copy('index_14.json', index_dir, 'index.json')
        sign(index_path, 'device-signing.gpg')
        setup_index('index_14.json', self._serverdir, 'device-signing.gpg')
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
        with patch('systemimage.reboot.Reboot.reboot') as reboot:
            mediator.download()
        # No reboot got issued.
        self.assertFalse(reboot.called)
        # But the command file did get written, and all the files are present.
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
    def test_reboot(self):
        # Run the intermediate steps, and finish with a reboot.
        self._setup_server_keyrings()
        mediator = Mediator()
        # Mock to check the state of reboot.
        with patch('systemimage.reboot.Reboot.reboot') as reboot:
            mediator.check_for_update()
            mediator.download()
            self.assertFalse(reboot.called)
            mediator.reboot()
            self.assertTrue(reboot.called)

    @configuration
    def test_factory_reset(self):
        mediator = Mediator()
        with patch('systemimage.reboot.Reboot.reboot') as reboot:
            mediator.factory_reset()
        self.assertTrue(reboot.called)
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, dedent("""\
            format data
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

    @unittest.skip('XXX FIXME UDM ONLY')
    @configuration
    def test_pause_resume(self):
        # Pause and resume the download.
        self._setup_server_keyrings()
        for path in ('3/4/5.txt', '4/5/6.txt', '5/6/7.txt'):
            full_path = os.path.join(self._serverdir, path)
            with open(full_path, 'wb') as fp:
                fp.write(b'x' * 100 * MiB)
        # We must update the file checksums in the index.json file, then we
        # have to resign it.
        index_path = os.path.join(
            self._serverdir, 'stable', 'nexus7', 'index.json')
        with open(index_path, 'r', encoding='utf-8') as fp:
            index = json.load(fp)
        checksum = sha256(b'x' * 100 * MiB).hexdigest()
        for i in range(3):
            index['images'][0]['files'][i]['checksum'] = checksum
        with open(index_path, 'w', encoding='utf-8') as fp:
            json.dump(index, fp)
        sign(index_path, 'device-signing.gpg')
        # Now the test is all set up.
        mediator = Mediator()
        pauses = []
        def do_paused(self, signal, path, paused):
            if paused:
                pauses.append(datetime.now())
        resumes = []
        def do_resumed(self, signal, path, resumed):
            if resumed:
                resumes.append(datetime.now())
        def pause_on_start(self, signal, path, started):
            if started and self._pausable:
                mediator.pause()
                GLib.timeout_add_seconds(3, mediator.resume)
        with ExitStack() as resources:
            resources.enter_context(
                patch('systemimage.udm.DownloadReactor._do_paused',
                      do_paused))
            resources.enter_context(
                patch('systemimage.udm.DownloadReactor._do_resumed',
                      do_resumed))
            resources.enter_context(
                patch('systemimage.udm.DownloadReactor._do_started',
                      pause_on_start))
            mediator.check_for_update()
            # We'll get a signature error because we messed with the file
            # contents.  Since this check happens after all files are
            # downloaded, this exception is inconsequential to the thing we're
            # testing.
            try:
                mediator.download()
            except SignatureError:
                pass
        # There should be at one pause and one resume event, separated by
        # about 3 seconds.
        self.assertEqual(len(pauses), 1)
        self.assertEqual(len(resumes), 1)
        self.assertGreaterEqual(resumes[0] - pauses[0], timedelta(seconds=2.5))

    @configuration
    def test_state_machine_exceptions(self, ini_file):
        # An exception in the state machine captures the exception and returns
        # an error string in the Update instance.
        self._setup_server_keyrings()
        config = Configuration(ini_file)
        with chmod(config.updater.cache_partition, 0):
            update = Mediator().check_for_update()
        # There's no winning path, but there is an error.
        self.assertFalse(update.is_available)
        self.assertIn('Permission denied', update.error)
