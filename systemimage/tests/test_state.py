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

"""Test the state machine."""

__all__ = [
    'TestChannelAlias',
    'TestCommandFileDelta',
    'TestCommandFileFull',
    'TestDailyProposed',
    'TestFileOrder',
    'TestPersistence',
    'TestRebooting',
    'TestState',
    'TestStateNewChannelsFormat',
    ]


import os
import hashlib
import unittest

from contextlib import ExitStack
from datetime import datetime, timezone
from subprocess import CalledProcessError
from systemimage.config import config
from systemimage.gpg import SignatureError
from systemimage.state import State
from systemimage.testing.demo import DemoDevice
from systemimage.testing.helpers import (
    configuration, copy, data_path, get_index, make_http_server, setup_index,
    setup_keyring_txz, setup_keyrings, sign, temporary_directory, touch_build)
from systemimage.testing.nose import SystemImagePlugin
from unittest.mock import patch


class TestState(unittest.TestCase):
    """Test various state transitions."""

    @classmethod
    def setUpClass(self):
        SystemImagePlugin.controller.set_mode(cert_pem='cert.pem')

    def setUp(self):
        self._stack = ExitStack()
        self._state = State()
        try:
            self._serverdir = self._stack.enter_context(temporary_directory())
            self._stack.push(make_http_server(
                self._serverdir, 8943, 'cert.pem', 'key.pem'))
            copy('channels_01.json', self._serverdir, 'channels.json')
            self._channels_path = os.path.join(
                self._serverdir, 'channels.json')
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    @configuration
    def test_first_signature_fails_get_new_image_signing_key(self):
        # The first time we check the channels.json file, the signature fails,
        # because it's blacklisted.  Everything works out in the end though
        # because a new system image signing key is downloaded.
        #
        # Start by signing the channels file with a blacklisted key.
        sign(self._channels_path, 'spare.gpg')
        setup_keyrings()
        # Make the spare keyring the image signing key, which would normally
        # make the channels.json signature good, except that we're going to
        # blacklist it.
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(config.gpg.image_signing))
        # Blacklist the spare keyring.
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        # Here's the new image signing key.
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(self._serverdir, 'gpg', 'image-signing.tar.xz'))
        # Run through the state machine twice so that we get the blacklist and
        # the channels.json file.  Since the channels.json file will not be
        # signed correctly, new state transitions will be added to re-aquire a
        # new image signing key.
        state = State()
        state.run_thru('get_channel')
        # Where we would expect a channels object, there is none.
        self.assertIsNone(state.channels)
        # Just to prove that the image signing key is going to change, let's
        # calculate the current one's checksum.
        with open(config.gpg.image_signing, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        next(state)
        # Now we have a new image signing key.
        with open(config.gpg.image_signing, 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest())
        # Let's re-sign the channels.json file with the new image signing
        # key.  Then step the state machine once more and we should get a
        # valid channels object.
        sign(self._channels_path, 'image-signing.gpg')
        next(state)
        self.assertEqual(state.channels.stable.devices.nexus7.index,
                         '/stable/nexus7/index.json')

    @configuration
    def test_first_signature_fails_get_bad_image_signing_key(self):
        # The first time we check the channels.json file, the signature fails.
        # We try to get the new image signing key, but it is bogus.
        setup_keyrings()
        # Start by signing the channels file with a blacklisted key.
        sign(self._channels_path, 'spare.gpg')
        # Make the new image signing key bogus by not signing it with the
        # image master key.
        setup_keyring_txz(
            'image-signing.gpg', 'spare.gpg', dict(type='image-signing'),
            os.path.join(self._serverdir, 'gpg', 'image-signing.tar.xz'))
        # Run through the state machine twice so that we get the blacklist and
        # the channels.json file.  Since the channels.json file will not be
        # signed correctly, new state transitions will be added to re-aquire a
        # new image signing key.
        state = State()
        state.run_thru('get_channel')
        # Where we would expect a channels object, there is none.
        self.assertIsNone(state.channels)
        # Just to prove that the image signing key is not going to change,
        # let's calculate the current one's checksum.
        with open(config.gpg.image_signing, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # The next state transition will attempt to get the new image signing
        # key, but that will fail because it is not signed correctly.
        self.assertRaises(SignatureError, next, state)
        # And the old image signing key hasn't changed.
        with open(config.gpg.image_signing, 'rb') as fp:
            self.assertEqual(checksum, hashlib.md5(fp.read()).digest())

    @configuration
    def test_bad_system_image_master_exposed_by_blacklist(self):
        # The blacklist is signed by the image master key.  If the blacklist's
        # signature is bad, the state machine will attempt to download a new
        # image master key.
        setup_keyrings()
        # Start by creating a blacklist signed by a bogus key, along with a
        # new image master key.
        setup_keyring_txz(
            'spare.gpg', 'spare.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        setup_keyring_txz(
            'spare.gpg', 'archive-master.gpg', dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        # Run the state machine once to grab the blacklist.  This should fail
        # with a signature error (internally).  There will be no blacklist.
        state = State()
        next(state)
        self.assertIsNone(state.blacklist)
        # Just to prove that the system image master key is going to change,
        # let's calculate the current one's checksum.
        with open(config.gpg.image_master, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # The next state transition should get us a new image master.
        next(state)
        # Now we have a new system image master key.
        with open(config.gpg.image_master, 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest())
        # Now the blacklist file's signature should be good.
        next(state)
        self.assertEqual(os.path.basename(state.blacklist), 'blacklist.tar.xz')

    @configuration
    def test_bad_system_image_master_new_one_is_no_better(self):
        # The blacklist is signed by the system image master key.  If the
        # blacklist's signature is bad, the state machine will attempt to
        # download a new system image master key.  In this case, the signature
        # on the new system image master key is bogus.
        setup_keyrings()
        # Start by creating a blacklist signed by a bogus key, along with a
        # new image master key.
        setup_keyring_txz(
            'spare.gpg', 'spare.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        setup_keyring_txz(
            'spare.gpg', 'spare.gpg', dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        # Run the state machine once to grab the blacklist.  This should fail
        # with a signature error (internally).  There will be no blacklist.
        state = State()
        next(state)
        self.assertIsNone(state.blacklist)
        # Just to provide that the system image master key is going to change,
        # let's calculate the current one's checksum.
        with open(config.gpg.image_master, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # The next state transition should get us a new image master, but its
        # signature is not good.
        self.assertRaises(SignatureError, next, state)
        # And the old system image master key hasn't changed.
        with open(config.gpg.image_master, 'rb') as fp:
            self.assertEqual(checksum, hashlib.md5(fp.read()).digest())

    @configuration
    def test_image_master_is_missing(self):
        # The system only comes pre-seeded with the archive master public
        # keyring.  All others are downloaded.
        setup_keyrings('archive-master')
        # Put a system image master key on the server.
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        # Run the state machine once to get the blacklist.  This should
        # download the system image master key, which will be signed against
        # the archive master.  Prove that the image master doesn't exist yet.
        self.assertFalse(os.path.exists(config.gpg.image_master))
        next(State())
        # Now the image master key exists.
        self.assertTrue(os.path.exists(config.gpg.image_master))

    @configuration
    def test_image_master_is_missing_with_blacklist(self):
        # The system only comes pre-seeded with the archive master public
        # keyring.  All others are downloaded.  This time there is a
        # blacklist and downloading that will also get the image master key.
        setup_keyrings('archive-master')
        # Put a system image master key on the server.
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        setup_keyring_txz(
            'spare.gpg', 'spare.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        # Run the state machine once to get the blacklist.  This should
        # download the system image master key, which will be signed against
        # the archive master.  Prove that the image master doesn't exist yet.
        self.assertFalse(os.path.exists(config.gpg.image_master))
        next(State())
        # Now the image master key exists.
        self.assertTrue(os.path.exists(config.gpg.image_master))

    @configuration
    def test_image_signing_is_missing(self):
        # The system only comes pre-seeded with the archive master public
        # keyring.  All others are downloaded.
        setup_keyrings('archive-master')
        # Put a system image master key on the server.
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        # Put an image signing key on the server.
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(self._serverdir, 'gpg', 'image-signing.tar.xz'))
        sign(self._channels_path, 'image-signing.gpg')
        # Run the state machine twice.  The first time downloads the
        # blacklist, which triggers a download of the image master key.  The
        # second one grabs the channels.json file which triggers a download of
        # the image signing key.  Prove that the image master and signing keys
        # dont exist yet.
        self.assertFalse(os.path.exists(config.gpg.image_master))
        self.assertFalse(os.path.exists(config.gpg.image_signing))
        state = State()
        state.run_thru('get_channel')
        # Now the image master and signing keys exist.
        self.assertTrue(os.path.exists(config.gpg.image_master))
        self.assertTrue(os.path.exists(config.gpg.image_signing))

    @configuration
    def test_downloaded_image_signing_is_still_bad(self):
        # LP: #1191979: Let's say there's a blacklist.tar.xz file but it is
        # not signed with the system image master key.  The state machine will
        # catch the SignatureError and re-download the system image master.
        # But let's say that the signature still fails (perhaps because the
        # blacklist was signed with the wrong key).  The client should log the
        # second signature failure and quit.
        setup_keyrings()
        # Put a blacklist file up that is signed by a bogus key.  Also, put up
        # the real image master key.  The blacklist verification check will
        # never succeed.
        setup_keyring_txz(
            'spare.gpg', 'spare.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        # Run the state machine three times:
        # blacklist -(sig fail)-> get master -> blacklist (sig fail)
        state = State()
        state.run_thru('get_master_key')
        self.assertRaises(SignatureError, next, state)


class _StateTestsBase(unittest.TestCase):
    # Must override in base classes.
    INDEX_FILE = None
    CHANNEL_FILE = None
    CHANNEL = None
    DEVICE = None

    # For more detailed output.
    maxDiff = None

    @classmethod
    def setUpClass(self):
        SystemImagePlugin.controller.set_mode(cert_pem='cert.pem')

    def setUp(self):
        self._stack = ExitStack()
        self._state = State()
        try:
            self._serverdir = self._stack.enter_context(temporary_directory())
            # Start up both an HTTPS and HTTP server.  The data files are
            # vended over the latter, everything else, over the former.
            self._stack.push(make_http_server(
                self._serverdir, 8943, 'cert.pem', 'key.pem'))
            self._stack.push(make_http_server(self._serverdir, 8980))
            # Set up the server files.
            assert self.CHANNEL_FILE is not None, (
                'Subclasses must set CHANNEL_FILE')
            copy(self.CHANNEL_FILE, self._serverdir, 'channels.json')
            sign(os.path.join(self._serverdir, 'channels.json'),
                 'image-signing.gpg')
            assert self.CHANNEL is not None, 'Subclasses must set CHANNEL'
            assert self.DEVICE is not None, 'Subclasses must set DEVICE'
            index_path = os.path.join(
                self._serverdir, self.CHANNEL, self.DEVICE, 'index.json')
            head, tail = os.path.split(index_path)
            assert self.INDEX_FILE is not None, (
                'Subclasses must set INDEX_FILE')
            copy(self.INDEX_FILE, head, tail)
            sign(index_path, 'device-signing.gpg')
            setup_index(self.INDEX_FILE, self._serverdir, 'device-signing.gpg')
        except:
            self._stack.close()
            raise

    def tearDown(self):
        self._stack.close()

    def _setup_keyrings(self):
        # Only the archive-master key is pre-loaded.  All the other keys
        # are downloaded and there will be both a blacklist and device
        # keyring.  The four signed keyring tar.xz files and their
        # signatures end up in the proper location after the state machine
        # runs to completion.
        setup_keyrings('archive-master')
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        setup_keyring_txz(
            'image-master.gpg', 'archive-master.gpg',
            dict(type='image-master'),
            os.path.join(self._serverdir, 'gpg', 'image-master.tar.xz'))
        setup_keyring_txz(
            'image-signing.gpg', 'image-master.gpg',
            dict(type='image-signing'),
            os.path.join(self._serverdir, 'gpg', 'image-signing.tar.xz'))
        setup_keyring_txz(
            'device-signing.gpg', 'image-signing.gpg',
            dict(type='device-signing'),
            os.path.join(self._serverdir, self.CHANNEL, self.DEVICE,
                         'device-signing.tar.xz'))


class TestRebooting(_StateTestsBase):
    """Test various state transitions leading to a reboot."""

    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_keyrings_copied_to_upgrader_paths(self):
        # The following keyrings get copied to system paths that the upgrader
        # consults:
        # * blacklist.tar.xz{,.asc}      - data partition (if one exists)
        # * image-master.tar.xz{,.asc}   - cache partition
        # * image-signing.tar.xz{,.asc}  - cache partition
        # * device-signing.tar.xz{,.asc} - cache partition (if one exists)
        self._setup_keyrings()
        cache_dir = config.updater.cache_partition
        data_dir = config.updater.data_partition
        blacklist_path = os.path.join(data_dir, 'blacklist.tar.xz')
        master_path = os.path.join(cache_dir, 'image-master.tar.xz')
        signing_path = os.path.join(cache_dir, 'image-signing.tar.xz')
        device_path = os.path.join(cache_dir, 'device-signing.tar.xz')
        # None of the keyrings or .asc files are found yet.
        self.assertFalse(os.path.exists(blacklist_path))
        self.assertFalse(os.path.exists(master_path))
        self.assertFalse(os.path.exists(signing_path))
        self.assertFalse(os.path.exists(device_path))
        self.assertFalse(os.path.exists(blacklist_path + '.asc'))
        self.assertFalse(os.path.exists(master_path + '.asc'))
        self.assertFalse(os.path.exists(signing_path + '.asc'))
        self.assertFalse(os.path.exists(device_path + '.asc'))
        # None of the data files are found yet.
        for image in get_index('index_13.json').images:
            for filerec in image.files:
                path = os.path.join(cache_dir, os.path.basename(filerec.path))
                asc = os.path.join(
                    cache_dir, os.path.basename(filerec.signature))
                self.assertFalse(os.path.exists(path))
                self.assertFalse(os.path.exists(asc))
        # Run the state machine enough times to download all the keyrings and
        # data files, then to move the files into place just before a reboot
        # is issued.  Steps preceded by * are steps that fail.
        # *get blacklist/get master -> get channels/signing
        # -> get device signing -> get index -> calculate winner
        # -> download files -> move files
        state = State()
        state.run_thru('move_files')
        # All of the keyrings and .asc files are found.
        self.assertTrue(os.path.exists(blacklist_path))
        self.assertTrue(os.path.exists(master_path))
        self.assertTrue(os.path.exists(signing_path))
        self.assertTrue(os.path.exists(device_path))
        self.assertTrue(os.path.exists(blacklist_path + '.asc'))
        self.assertTrue(os.path.exists(master_path + '.asc'))
        self.assertTrue(os.path.exists(signing_path + '.asc'))
        self.assertTrue(os.path.exists(device_path + '.asc'))
        # All of the data files are found.
        for image in get_index('index_13.json').images:
            for filerec in image.files:
                path = os.path.join(cache_dir, os.path.basename(filerec.path))
                asc = os.path.join(
                    cache_dir, os.path.basename(filerec.signature))
                self.assertTrue(os.path.exists(path))
                self.assertTrue(os.path.exists(asc))

    @configuration
    def test_reboot_issued(self):
        # The reboot gets issued.
        self._setup_keyrings()
        with patch('systemimage.reboot.check_call') as mock:
            list(State())
        self.assertEqual(mock.call_args[0][0],
                         ['/sbin/reboot', '-f', 'recovery'])

    @configuration
    def test_no_update_available_no_reboot(self):
        # LP: #1202915.  If there's no update available, running the state
        # machine to completion should not result in a reboot.
        self._setup_keyrings()
        # Hack the current build number so that no update is available.
        touch_build(20250000)
        with patch('systemimage.reboot.Reboot.reboot') as mock:
            list(State())
        self.assertEqual(mock.call_count, 0)

    @unittest.skipIf(os.getuid() == 0, 'This test would actually reboot!')
    @configuration
    def test_reboot_fails(self):
        # The reboot fails, e.g. because we are not root.
        self._setup_keyrings()
        self.assertRaises(CalledProcessError, list, State())

    @configuration
    def test_run_until(self):
        # It is possible to run the state machine either until some specific
        # state is completed, or it runs to the end.
        self._setup_keyrings()
        state = State()
        self.assertIsNone(state.channels)
        state.run_thru('get_channel')
        self.assertIsNotNone(state.channels)
        # But there is no index file yet.
        self.assertIsNone(state.index)
        # Run it some more.
        state.run_thru('get_index')
        self.assertIsNotNone(state.index)
        # Run until just before the reboot.
        #
        # Mock the reboot to make sure a reboot did not get issued.
        got_reboot = False
        def reboot_mock(self):
            nonlocal got_reboot
            got_reboot = True
        with patch('systemimage.reboot.Reboot.reboot', reboot_mock):
            state.run_until('reboot')
        # No reboot got issued.
        self.assertFalse(got_reboot)
        # Finish it off.
        with patch('systemimage.reboot.Reboot.reboot', reboot_mock):
            list(state)
        self.assertTrue(got_reboot)


class TestCommandFileFull(_StateTestsBase):
    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_full_command_file(self):
        # A full update's command file gets properly filled.
        self._setup_keyrings()
        State().run_until('reboot')
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


class TestCommandFileDelta(_StateTestsBase):
    INDEX_FILE = 'index_15.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_delta_command_file(self):
        # A delta update's command file gets properly filled.
        self._setup_keyrings()
        # Set the current build number so a delta update will work.
        touch_build(20120100)
        State().run_until('reboot')
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, """\
load_keyring image-master.tar.xz image-master.tar.xz.asc
load_keyring image-signing.tar.xz image-signing.tar.xz.asc
load_keyring device-signing.tar.xz device-signing.tar.xz.asc
mount system
update 6.txt 6.txt.asc
update 7.txt 7.txt.asc
update 5.txt 5.txt.asc
unmount system
""")


class TestFileOrder(_StateTestsBase):
    INDEX_FILE = 'index_16.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_file_order(self):
        # Updates are applied sorted first by image positional order, then
        # within the image by the 'order' key.
        self._setup_keyrings()
        # Set the current build number so a delta update will work.
        touch_build(20120100)
        State().run_until('reboot')
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, """\
load_keyring image-master.tar.xz image-master.tar.xz.asc
load_keyring image-signing.tar.xz image-signing.tar.xz.asc
load_keyring device-signing.tar.xz device-signing.tar.xz.asc
format system
mount system
update a.txt a.txt.asc
update b.txt b.txt.asc
update c.txt c.txt.asc
update d.txt d.txt.asc
update e.txt e.txt.asc
update f.txt f.txt.asc
update g.txt g.txt.asc
update h.txt h.txt.asc
update i.txt i.txt.asc
unmount system
""")


@unittest.skip('persistence is temporarily disabled')
class TestPersistence(_StateTestsBase):
    """Test the State object's persistence."""

    INDEX_FILE = 'index_16.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_pickle_file(self):
        # Run the state machine through the 'persist' state.  Create a new
        # state object which restores the persisted state.
        self._setup_keyrings()
        self.assertFalse(os.path.exists(config.system.state_file))
        state = State()
        self.assertIsNone(state.winner)
        state.run_thru('persist')
        self.assertIsNotNone(state.winner)
        self.assertTrue(os.path.exists(config.system.state_file))
        state = State()
        self.assertIsNotNone(state.winner)

    @configuration
    def test_no_update_no_pickle_file(self):
        # If there's no update, there's no state file.
        self._setup_keyrings()
        touch_build(20250000)
        self.assertFalse(os.path.exists(config.system.state_file))
        state = State()
        self.assertIsNone(state.winner)
        state.run_thru('persist')
        self.assertEqual(state.winner, [])
        self.assertFalse(os.path.exists(config.system.state_file))
        state = State()
        self.assertIsNone(state.winner)


class TestDailyProposed(_StateTestsBase):
    """Test that the daily-proposed channel works as expected."""

    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_07.json'
    CHANNEL = 'daily-proposed'
    DEVICE = 'grouper'

    @configuration
    def test_daily_proposed_channel(self):
        # Resolve the index.json path for a channel with a dash in it.
        self._setup_keyrings()
        state = State()
        self._stack.enter_context(
            patch('systemimage.state.config.channel', 'daily-proposed'))
        self._stack.enter_context(
            patch('systemimage.state.config.hooks.device', DemoDevice))
        state.run_thru('get_index')
        self.assertEqual(state.index.global_.generated_at,
                         datetime(2013, 8, 1, 8, 1, tzinfo=timezone.utc))

    @configuration
    def test_bogus_channel(self):
        # Try and fail to resolve the index.json path for a non-existent
        # channel with a dash in it.
        self._setup_keyrings()
        state = State()
        self._stack.enter_context(
            patch('systemimage.state.config.channel', 'daily-testing'))
        self._stack.enter_context(
            patch('systemimage.state.config.hooks.device', DemoDevice))
        state.run_thru('get_index')
        self.assertIsNone(state.index)


class TestVersionedProposed(_StateTestsBase):
    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_08.json'
    CHANNEL = '14.04-proposed'
    DEVICE = 'grouper'

    @configuration
    def test_version_proposed_channel(self):
        # Resolve the index.json path for a channel with a dash and a dot in
        # it.
        self._setup_keyrings()
        state = State()
        self._stack.enter_context(
            patch('systemimage.state.config.channel', '14.04-proposed'))
        self._stack.enter_context(
            patch('systemimage.state.config.hooks.device', DemoDevice))
        state.run_thru('get_index')
        self.assertEqual(state.index.global_.generated_at,
                         datetime(2013, 8, 1, 8, 1, tzinfo=timezone.utc))


class TestFilters(_StateTestsBase):
    INDEX_FILE = 'index_15.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_filter_none(self):
        # With no filter, we get the unadulterated candidate paths.
        self._setup_keyrings()
        touch_build(20120100)
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual(len(state.winner), 1)

    @configuration
    def test_filter_1(self):
        # The state machine can use a filter to come up with a different set
        # of candidate upgrade paths.  In this case, no candidates.
        self._setup_keyrings()
        touch_build(20120100)
        def filter_out_everything(candidates):
            return []
        state = State(candidate_filter=filter_out_everything)
        state.run_thru('calculate_winner')
        self.assertEqual(len(state.winner), 0)


class TestStateNewChannelsFormat(_StateTestsBase):
    CHANNEL_FILE = 'channels_09.json'
    CHANNEL = 'saucy'
    DEVICE = 'manta'
    INDEX_FILE = 'index_21.json'

    @configuration
    def test_full_reboot(self, ini_file):
        # Test that state transitions through reboot work for the new channel
        # format.  Also check that the right files get moved into place.
        self._stack.enter_context(patch('systemimage.device.check_output',
                                        return_value='manta'))
        config.load(data_path('channel_04.ini'), override=True)
        self._setup_keyrings()
        state = State()
        state.run_until('reboot')
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        with open(path, 'r', encoding='utf-8') as fp:
            command = fp.read()
        self.assertMultiLineEqual(command, """\
load_keyring image-master.tar.xz image-master.tar.xz.asc
load_keyring image-signing.tar.xz image-signing.tar.xz.asc
load_keyring device-signing.tar.xz device-signing.tar.xz.asc
mount system
update 6.txt 6.txt.asc
update 7.txt 7.txt.asc
update 5.txt 5.txt.asc
unmount system
""")
        got_reboot = False
        def reboot_mock(self):
            nonlocal got_reboot
            got_reboot = True
        with patch('systemimage.reboot.Reboot.reboot', reboot_mock):
            list(state)
        self.assertTrue(got_reboot)


class TestChannelAlias(_StateTestsBase):
    CHANNEL_FILE = 'channels_10.json'
    CHANNEL = 'daily'
    DEVICE = 'manta'
    INDEX_FILE = 'index_20.json'

    @configuration
    def test_channel_alias_switch(self, ini_file):
        # Channels in the channel.json files can have an optional "alias" key,
        # which if set, describes the other channel this channel is based on
        # (only in a server-side generated way; the client sees all channels
        # as fully "stocked").
        #
        # The channel.ini file can have a channel_target key which names the
        # channel alias this device has been tracking.  If the channel_target
        # does not match the channel alias, then the client considers its
        # internal version number to be 0 and does a full update.
        #
        # This is used to support version downgrades when changing the alias
        # to point to a different series (LP: #1221844).
        #
        # Here's an example.  Let's say a device has been tracking the 'daily'
        # channel, which is aliased to 'saucy'.  Suddenly, Tubular Tapir is
        # released and the 'daily' channel is aliased to 'tubular'.  When the
        # device goes to update, it sees that it was tracking the saucy alias
        # and now must track the tubular alias, so it needs to do a full
        # upgrade from build number 0 to get on the right track.
        #
        # To test this condition, we calculate the upgrade path first in the
        # absence of a channels.ini file.  The device is tracking the daily
        # channel, and there isno channel_target attribute, so we get the
        # latest build on that channel.
        self._stack.enter_context(patch('systemimage.device.check_output',
                                        return_value='manta'))
        self._setup_keyrings()
        touch_build(300)
        config.channel = 'daily'
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual([image.version for image in state.winner],
                         [301, 304])
        # Here's what the upgrade path would be if we were using a build
        # number of 0 (ignoring any channel alias switching).
        del config.build_number
        touch_build(0)
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual([image.version for image in state.winner],
                         [200, 201, 304])
        # Set the build number back to 300 for the next test.
        del config.build_number
        touch_build(300)
        # Now we pretend there was a channel.ini file, and load it.  This also
        # tells us the current build number is 300, but through the
        # channel_target field it tells us that the previous daily channel
        # alias was saucy.  Now (via the channels.json file) it's tubular, and
        # the upgrade path starting at build 0 is different.
        config.load(data_path('channel_05.ini'), override=True)
        # All things being equal to the first test above, except that now
        # we're in the middle of an alias switch.  The upgrade path is exactly
        # the same as if we were upgrading from build 0.
        self.assertEqual(config.build_number, 300)
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual([image.version for image in state.winner],
                         [200, 201, 304])

    @configuration
    def test_channel_alias_switch_with_cli_option(self, ini_file):
        # Like the above test, but in similating the use of `system-image-cli
        # --build 300`, we set the build number explicitly.  This prevent the
        # channel alias squashing of the build number to 0.
        self._stack.enter_context(patch('systemimage.device.check_output',
                                        return_value='manta'))
        self._setup_keyrings()
        # This sets the build number via the /etc/ubuntu_build file.
        touch_build(300)
        config.channel = 'daily'
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual([image.version for image in state.winner],
                         [301, 304])
        # Now we pretend there was a channel.ini file, and load it.  This also
        # tells us the current build number is 300, but through the
        # channel_target field it tells us that the previous daily channel
        # alias was saucy.  Now (via the channels.json file) it's tubular.
        config.load(data_path('channel_05.ini'), override=True)
        # All things being equal to the first test above, except that now
        # we're in the middle of an alias switch.  The upgrade path is exactly
        # the same as if we were upgrading from build 0.
        del config.build_number
        self.assertEqual(config.build_number, 300)
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual([image.version for image in state.winner],
                         [200, 201, 304])
        # Finally, this mimic the effect of --build 300, thus giving us back
        # the original upgrade path.
        config.build_number = 300
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual([image.version for image in state.winner],
                         [301, 304])
