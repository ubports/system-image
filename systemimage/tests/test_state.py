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
    'TestCachedFiles',
    'TestChannelAlias',
    'TestCommandFileDelta',
    'TestCommandFileFull',
    'TestDailyProposed',
    'TestFileOrder',
    'TestKeyringDoubleChecks',
    'TestPhasedUpdates',
    'TestRebooting',
    'TestState',
    'TestStateNewChannelsFormat',
    ]


import os
import shutil
import hashlib
import unittest

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from functools import partial
from subprocess import CalledProcessError
from systemimage.config import config
from systemimage.gpg import Context, SignatureError
from systemimage.state import State
from systemimage.testing.demo import DemoDevice
from systemimage.testing.helpers import (
    ServerTestBase, configuration, copy, data_path, get_index,
    make_http_server, setup_keyring_txz, setup_keyrings, sign,
    temporary_directory, touch_build)
from systemimage.testing.nose import SystemImagePlugin
# FIXME
from systemimage.tests.test_candidates import _descriptions
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
    def test_cleanup(self):
        # All residual files from the data partitions are removed.  The cache
        # partition is not touched (that clean up happens later).
        wopen = partial(open, mode='w', encoding='utf-8')
        cache_partition = config.updater.cache_partition
        data_partition = config.updater.data_partition
        with wopen(os.path.join(cache_partition, 'log')) as fp:
            print('logger keeper', file=fp)
        with wopen(os.path.join(cache_partition, 'last_log')) as fp:
            print('logger keeper', file=fp)
        with wopen(os.path.join(cache_partition, 'xxx.txt')) as fp:
            print('xxx', file=fp)
        with wopen(os.path.join(cache_partition, 'yyy.txt')) as fp:
            print('yyy', file=fp)
        with wopen(os.path.join(data_partition, 'log')) as fp:
            print('stale log', file=fp)
        with wopen(os.path.join(data_partition, 'last_log')) as fp:
            print('stale log', file=fp)
        with wopen(os.path.join(data_partition, 'blacklist.tar.xz')) as fp:
            print('black list', file=fp)
        with wopen(os.path.join(data_partition, 'blacklist.tar.xz.asc')) as fp:
            print('black list', file=fp)
        with wopen(os.path.join(data_partition, 'keyring.tar.xz')) as fp:
            print('black list', file=fp)
        with wopen(os.path.join(data_partition, 'keyring.tar.xz.asc')) as fp:
            print('black list', file=fp)
        # Here are all the files before we start up the state machine.
        self.assertEqual(len(os.listdir(cache_partition)), 4)
        self.assertEqual(len(os.listdir(data_partition)), 6)
        # Clean up step.
        State().run_thru('cleanup')
        # The blacklist and keyring files are removed from the data partition.
        contents = os.listdir(data_partition)
        self.assertEqual(len(contents), 2)
        self.assertNotIn('blacklist.tar.xz', contents)
        self.assertNotIn('blacklist.tar.xz.asc', contents)
        self.assertNotIn('keyring.tar.xz', contents)
        self.assertNotIn('keyring.tar.xz.asc', contents)
        # None of the files in the cache partition are removed.
        self.assertEqual(set(os.listdir(cache_partition)),
                         set(['log', 'last_log', 'xxx.txt', 'yyy.txt']))

    @configuration
    def test_cleanup_no_partition(self):
        # If one or more of the partitions doesn't exist, no big deal.
        #
        # The cache partition doesn't exist.
        os.rename(config.updater.cache_partition,
                  config.updater.cache_partition + '.aside')
        State().run_thru('cleanup')
        # The data partition doesn't exist.
        os.rename(config.updater.cache_partition + '.aside',
                  config.updater.cache_partition)
        os.rename(config.updater.data_partition,
                  config.updater.data_partition + '.aside')
        State().run_thru('cleanup')
        # Neither partitions exist.
        os.rename(config.updater.cache_partition,
                  config.updater.cache_partition + '.aside')
        State().run_thru('cleanup')

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
        # Run the state machine long enough to grab the blacklist.  This
        # should fail with a signature error (internally).  There will be no
        # blacklist.
        state = State()
        state.run_thru('get_blacklist_1')
        self.assertIsNone(state.blacklist)
        # Just to prove that the system image master key is going to change,
        # let's calculate the current one's checksum.
        with open(config.gpg.image_master, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # The next state transition should get us a new image master.
        state.run_until('get_blacklist_2')
        # Now we have a new system image master key.
        with open(config.gpg.image_master, 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest())
        # Now the blacklist file's signature should be good.
        state.run_thru('get_blacklist_2')
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
        # Run the state machine long enough to grab the blacklist.  This
        # should fail with a signature error (internally).  There will be no
        # blacklist.
        state = State()
        state.run_thru('get_blacklist_1')
        self.assertIsNone(state.blacklist)
        # Just to provide that the system image master key is going to change,
        # let's calculate the current one's checksum.
        with open(config.gpg.image_master, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # The next state transition should get us a new image master, but its
        # signature is not good.
        self.assertRaises(SignatureError, state.run_until, 'get_blacklist_2')
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
        # Run the state machine long enough to get the blacklist.  This should
        # download the system image master key, which will be signed against
        # the archive master.  Prove that the image master doesn't exist yet.
        self.assertFalse(os.path.exists(config.gpg.image_master))
        State().run_thru('get_blacklist_1')
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
        # Run the state machine log enough to get the blacklist.  This should
        # download the system image master key, which will be signed against
        # the archive master.  Prove that the image master doesn't exist yet.
        self.assertFalse(os.path.exists(config.gpg.image_master))
        State().run_thru('get_blacklist_1')
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


class TestRebooting(ServerTestBase):
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
        self._setup_server_keyrings()
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
        self._setup_server_keyrings()
        mock = self._enter(patch('systemimage.reboot.check_call'))
        list(State())
        self.assertEqual(mock.call_args[0][0],
                         ['/sbin/reboot', '-f', 'recovery'])

    @configuration
    def test_no_update_available_no_reboot(self):
        # LP: #1202915.  If there's no update available, running the state
        # machine to completion should not result in a reboot.
        self._setup_server_keyrings()
        # Hack the current build number so that no update is available.
        touch_build(5000)
        mock = self._enter(patch('systemimage.reboot.Reboot.reboot'))
        list(State())
        self.assertEqual(mock.call_count, 0)

    @unittest.skipIf(os.getuid() == 0, 'This test would actually reboot!')
    @configuration
    def test_reboot_fails(self):
        # The reboot fails, e.g. because we are not root.
        self._setup_server_keyrings()
        self.assertRaises(CalledProcessError, list, State())

    @configuration
    def test_run_until(self):
        # It is possible to run the state machine either until some specific
        # state is completed, or it runs to the end.
        self._setup_server_keyrings()
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


class TestRebootingNoDeviceSigning(ServerTestBase):
    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_11.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'
    SIGNING_KEY = 'image-signing.gpg'

    @configuration
    def test_keyrings_copied_to_upgrader_paths_no_device_keyring(self):
        # The following keyrings get copied to system paths that the upgrader
        # consults:
        # * blacklist.tar.xz{,.asc}      - data partition (if one exists)
        # * image-master.tar.xz{,.asc}   - cache partition
        # * image-signing.tar.xz{,.asc}  - cache partition
        #
        # In this test, there is no device signing keyring.
        self._setup_server_keyrings(device_signing=False)
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
        # All of the keyrings and .asc files are found, except for the device
        # singing keys.
        self.assertTrue(os.path.exists(blacklist_path))
        self.assertTrue(os.path.exists(master_path))
        self.assertTrue(os.path.exists(signing_path))
        self.assertFalse(os.path.exists(device_path))
        self.assertTrue(os.path.exists(blacklist_path + '.asc'))
        self.assertTrue(os.path.exists(master_path + '.asc'))
        self.assertTrue(os.path.exists(signing_path + '.asc'))
        self.assertFalse(os.path.exists(device_path + '.asc'))
        # All of the data files are found.
        for image in get_index('index_13.json').images:
            for filerec in image.files:
                path = os.path.join(cache_dir, os.path.basename(filerec.path))
                asc = os.path.join(
                    cache_dir, os.path.basename(filerec.signature))
                self.assertTrue(os.path.exists(path))
                self.assertTrue(os.path.exists(asc))


class TestCommandFileFull(ServerTestBase):
    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_full_command_file(self):
        # A full update's command file gets properly filled.
        self._setup_server_keyrings()
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

    @configuration
    def test_write_command_file_atomically(self):
        # LP: #1241236 - write the ubuntu_command file atomically.
        self._setup_server_keyrings()
        self._state.run_until('prepare_recovery')
        # This is a little proxy object which interposes printing.  When it
        # sees the string 'unmount system' written to it, it raises an
        # IOError.  We use this to prove that the ubuntu_command file is
        # written atomically.
        old_print = print
        def broken_print(arg0, *args, **kws):
            if arg0.startswith('unmount system'):
                raise IOError('barf')
            old_print(arg0, *args, **kws)
        with patch('builtins.print', broken_print):
            with self.assertRaises(IOError) as cm:
                next(self._state)
            self.assertEqual(str(cm.exception), 'barf')
        path = os.path.join(config.updater.cache_partition, 'ubuntu_command')
        self.assertFalse(os.path.exists(path))


class TestCommandFileDelta(ServerTestBase):
    INDEX_FILE = 'index_15.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_delta_command_file(self):
        # A delta update's command file gets properly filled.
        self._setup_server_keyrings()
        # Set the current build number so a delta update will work.
        touch_build(100)
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


class TestFileOrder(ServerTestBase):
    INDEX_FILE = 'index_16.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_file_order(self):
        # Updates are applied sorted first by image positional order, then
        # within the image by the 'order' key.
        self._setup_server_keyrings()
        # Set the current build number so a delta update will work.
        touch_build(100)
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


class TestDailyProposed(ServerTestBase):
    """Test that the daily-proposed channel works as expected."""

    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_07.json'
    CHANNEL = 'daily-proposed'
    DEVICE = 'grouper'

    @configuration
    def test_daily_proposed_channel(self):
        # Resolve the index.json path for a channel with a dash in it.
        self._setup_server_keyrings()
        state = State()
        self._enter(
            patch('systemimage.state.config.channel', 'daily-proposed'))
        self._enter(patch('systemimage.state.config.hooks.device', DemoDevice))
        state.run_thru('get_index')
        self.assertEqual(state.index.global_.generated_at,
                         datetime(2013, 8, 1, 8, 1, tzinfo=timezone.utc))

    @configuration
    def test_bogus_channel(self):
        # Try and fail to resolve the index.json path for a non-existent
        # channel with a dash in it.
        self._setup_server_keyrings()
        state = State()
        self._enter(patch('systemimage.state.config.channel', 'daily-testing'))
        self._enter(patch('systemimage.state.config.hooks.device', DemoDevice))
        state.run_thru('get_index')
        self.assertIsNone(state.index)


class TestVersionedProposed(ServerTestBase):
    INDEX_FILE = 'index_13.json'
    CHANNEL_FILE = 'channels_08.json'
    CHANNEL = '14.04-proposed'
    DEVICE = 'grouper'

    @configuration
    def test_version_proposed_channel(self):
        # Resolve the index.json path for a channel with a dash and a dot in
        # it.
        self._setup_server_keyrings()
        state = State()
        self._enter(
            patch('systemimage.state.config.channel', '14.04-proposed'))
        self._enter(patch('systemimage.state.config.hooks.device', DemoDevice))
        state.run_thru('get_index')
        self.assertEqual(state.index.global_.generated_at,
                         datetime(2013, 8, 1, 8, 1, tzinfo=timezone.utc))


class TestFilters(ServerTestBase):
    INDEX_FILE = 'index_15.json'
    CHANNEL_FILE = 'channels_06.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'

    @configuration
    def test_filter_none(self):
        # With no filter, we get the unadulterated candidate paths.
        self._setup_server_keyrings()
        touch_build(100)
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual(len(state.winner), 1)

    @configuration
    def test_filter_1(self):
        # The state machine can use a filter to come up with a different set
        # of candidate upgrade paths.  In this case, no candidates.
        self._setup_server_keyrings()
        touch_build(100)
        def filter_out_everything(candidates):
            return []
        state = State(candidate_filter=filter_out_everything)
        state.run_thru('calculate_winner')
        self.assertEqual(len(state.winner), 0)


class TestStateNewChannelsFormat(ServerTestBase):
    CHANNEL_FILE = 'channels_09.json'
    CHANNEL = 'saucy'
    DEVICE = 'manta'
    INDEX_FILE = 'index_21.json'

    @configuration
    def test_full_reboot(self):
        # Test that state transitions through reboot work for the new channel
        # format.  Also check that the right files get moved into place.
        self._enter(patch('systemimage.device.check_output',
                          return_value='manta'))
        config.load(data_path('channel_04.ini'), override=True)
        self._setup_server_keyrings()
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


class TestChannelAlias(ServerTestBase):
    CHANNEL_FILE = 'channels_10.json'
    CHANNEL = 'daily'
    DEVICE = 'manta'
    INDEX_FILE = 'index_20.json'

    @configuration
    def test_channel_alias_switch(self):
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
        self._enter(patch('systemimage.device.check_output',
                          return_value='manta'))
        self._setup_server_keyrings()
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
    def test_channel_alias_switch_with_cli_option(self):
        # Like the above test, but in similating the use of `system-image-cli
        # --build 300`, we set the build number explicitly.  This prevent the
        # channel alias squashing of the build number to 0.
        self._enter(patch('systemimage.device.check_output',
                          return_value='manta'))
        self._setup_server_keyrings()
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


class TestPhasedUpdates(ServerTestBase):
    CHANNEL_FILE = 'channels_10.json'
    CHANNEL = 'daily'
    DEVICE = 'manta'
    INDEX_FILE = 'index_22.json'

    @configuration
    def test_phased_updates(self):
        # With our threshold at 66, the "Full B" image is suppressed, thus the
        # upgrade path is different than it normally would be.  In this case,
        # the 'A' path is taken (in fact, the B path isn't even considered).
        self._enter(patch('systemimage.device.check_output',
                          return_value='manta'))
        self._setup_server_keyrings()
        self._enter(patch('systemimage.index.phased_percentage',
                          return_value=66))
        config.channel = 'daily'
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual(_descriptions(state.winner),
                         ['Full A', 'Delta A.1', 'Delta A.2'])

    @configuration
    def test_phased_updates_0(self):
        # With our threshold at 0, all images are good, so it's a "normal"
        # update path.
        self._enter(patch('systemimage.device.check_output',
                          return_value='manta'))
        self._setup_server_keyrings()
        self._enter(patch('systemimage.index.phased_percentage',
                          return_value=0))
        config.channel = 'daily'
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual(_descriptions(state.winner),
                         ['Full B', 'Delta B.1', 'Delta B.2'])

    @configuration
    def test_phased_updates_100(self):
        # With our threshold at 100, only the image without a specific
        # phased-percentage key is allowed.  That's the 'A' path again.
        self._enter(patch('systemimage.device.check_output',
                          return_value='manta'))
        self._setup_server_keyrings()
        self._enter(patch('systemimage.index.phased_percentage',
                          return_value=77))
        config.channel = 'daily'
        state = State()
        state.run_thru('calculate_winner')
        self.assertEqual(_descriptions(state.winner),
                         ['Full A', 'Delta A.1', 'Delta A.2'])


class TestCachedFiles(ServerTestBase):
    CHANNEL_FILE = 'channels_11.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'
    INDEX_FILE = 'index_13.json'
    SIGNING_KEY = 'image-signing.gpg'

    @configuration
    def test_all_files_are_cached(self):
        # All files in an upgrade are already downloaded, so all that's
        # necessary is to verify them but not re-download them.
        self._setup_server_keyrings()
        touch_build(0)
        # Run the state machine far enough to calculate the winning path.
        state = State()
        state.run_thru('calculate_winner')
        self.assertIsNotNone(state.winner)
        # Let's install all the data files into their final location.  The
        # signature files must be included.
        for path in ('3/4/5.txt', '4/5/6.txt', '5/6/7.txt'):
            data_file = os.path.join(self._serverdir, path)
            shutil.copy(data_file, config.updater.cache_partition)
            shutil.copy(data_file + '.asc', config.updater.cache_partition)
        def get_files(downloads, *args, **kws):
            if len(downloads) != 0:
                raise AssertionError('get_files() was called with downloads')
        state.downloader.get_files = get_files
        state.run_thru('download_files')
        # Yet all the data files should still be available.
        self.assertEqual(set(os.listdir(config.updater.cache_partition)),
                         set(('5.txt', '6.txt', '7.txt',
                              '5.txt.asc', '6.txt.asc', '7.txt.asc')))

    @configuration
    def test_some_files_are_cached(self):
        # Some of the files in an upgrade are already downloaded, so only
        # download the ones that are missing.
        self._setup_server_keyrings()
        touch_build(0)
        # Run the state machine far enough to calculate the winning path.
        state = State()
        state.run_thru('calculate_winner')
        self.assertIsNotNone(state.winner)
        # Let's install all the data files into their final location.  The
        # signature files must be included.
        for path in ('3/4/5.txt', '4/5/6.txt'):
            data_file = os.path.join(self._serverdir, path)
            shutil.copy(data_file, config.updater.cache_partition)
            shutil.copy(data_file + '.asc', config.updater.cache_partition)
        old_get_files = state.downloader.get_files
        def get_files(downloads, *args, **kws):
            if len(downloads) != 2:
                raise AssertionError('Unexpected get_files() call')
            for url, dst in downloads:
                if os.path.basename(url) != os.path.basename(dst):
                    raise AssertionError('Mismatched downloads')
                if os.path.basename(dst) not in ('7.txt', '7.txt.asc'):
                    raise AssertionError('Unexpected download')
            return old_get_files(downloads, *args, **kws)
        state.downloader.get_files = get_files
        state.run_thru('download_files')
        # Yet all the data files should still be available.
        self.assertEqual(set(os.listdir(config.updater.cache_partition)),
                         set(('5.txt', '6.txt', '7.txt',
                              '5.txt.asc', '6.txt.asc', '7.txt.asc')))

    @configuration
    def test_some_signature_files_are_missing(self):
        # Some of the signature files are missing, so we have to download both
        # the data and signature files.
        self._setup_server_keyrings()
        touch_build(0)
        # Run the state machine far enough to calculate the winning path.
        state = State()
        state.run_thru('calculate_winner')
        self.assertIsNotNone(state.winner)
        # Let's install all the data files into their final location.  The
        # signature files must be included.
        for path in ('3/4/5.txt', '4/5/6.txt', '5/6/7.txt'):
            data_file = os.path.join(self._serverdir, path)
            shutil.copy(data_file, config.updater.cache_partition)
            if os.path.basename(path) != '6.txt':
                shutil.copy(data_file + '.asc', config.updater.cache_partition)
        old_get_files = state.downloader.get_files
        def get_files(downloads, *args, **kws):
            if len(downloads) != 2:
                raise AssertionError('Unexpected get_files() call')
            for url, dst in downloads:
                if os.path.basename(url) != os.path.basename(dst):
                    raise AssertionError('Mismatched downloads')
                if os.path.basename(dst) not in ('6.txt', '6.txt.asc'):
                    raise AssertionError('Unexpected download')
            return old_get_files(downloads, *args, **kws)
        state.downloader.get_files = get_files
        state.run_thru('download_files')
        # Yet all the data files should still be available.
        self.assertEqual(set(os.listdir(config.updater.cache_partition)),
                         set(('5.txt', '6.txt', '7.txt',
                              '5.txt.asc', '6.txt.asc', '7.txt.asc')))

    @configuration
    def test_some_data_files_are_missing(self):
        # Some of the data files are missing, so we have to download both the
        # data and signature files.
        self._setup_server_keyrings()
        touch_build(0)
        # Run the state machine far enough to calculate the winning path.
        state = State()
        state.run_thru('calculate_winner')
        self.assertIsNotNone(state.winner)
        # Let's install all the data files into their final location.  The
        # signature files must be included.
        for path in ('3/4/5.txt', '4/5/6.txt', '5/6/7.txt'):
            data_file = os.path.join(self._serverdir, path)
            if os.path.basename(path) != '5.txt':
                shutil.copy(data_file, config.updater.cache_partition)
            shutil.copy(data_file + '.asc', config.updater.cache_partition)
        old_get_files = state.downloader.get_files
        def get_files(downloads, *args, **kws):
            if len(downloads) != 2:
                raise AssertionError('Unexpected get_files() call')
            for url, dst in downloads:
                if os.path.basename(url) != os.path.basename(dst):
                    raise AssertionError('Mismatched downloads')
                if os.path.basename(dst) not in ('5.txt', '5.txt.asc'):
                    raise AssertionError('Unexpected download')
            return old_get_files(downloads, *args, **kws)
        state.downloader.get_files = get_files
        state.run_thru('download_files')
        # Yet all the data files should still be available.
        self.assertEqual(set(os.listdir(config.updater.cache_partition)),
                         set(('5.txt', '6.txt', '7.txt',
                              '5.txt.asc', '6.txt.asc', '7.txt.asc')))

    @configuration
    def test_cached_signatures_are_blacklisted(self):
        # All files in an upgrade are already downloaded, but the key used to
        # sign the files has been blacklisted, so everything has to be
        # downloaded again.
        self._setup_server_keyrings()
        touch_build(0)
        # Run the state machine far enough to calculate the winning path.
        state = State()
        state.run_thru('calculate_winner')
        self.assertIsNotNone(state.winner)
        # Let's install all the data files into their final location.  The
        # signature files must be included.
        for path in ('3/4/5.txt', '4/5/6.txt', '5/6/7.txt'):
            data_file = os.path.join(self._serverdir, path)
            shutil.copy(data_file, config.updater.cache_partition)
            # Sign the file with what will be the blacklist.
            dst = os.path.join(config.updater.cache_partition,
                               os.path.basename(data_file))
            sign(dst, 'spare.gpg')
        # Set up the blacklist file.
        setup_keyring_txz(
            'spare.gpg', 'image-master.gpg', dict(type='blacklist'),
            os.path.join(self._serverdir, 'gpg', 'blacklist.tar.xz'))
        # All the files will be downloaded.
        requested_downloads = set()
        old_get_files = state.downloader.get_files
        def get_files(downloads, *args, **kws):
            for dst, url in downloads:
                requested_downloads.add(os.path.basename(dst))
            return old_get_files(downloads, *args, **kws)
        state.downloader.get_files = get_files
        state.run_thru('download_files')
        # All the files were re-downloaded.
        self.assertEqual(requested_downloads,
                         set(('5.txt', '5.txt.asc',
                              '6.txt', '6.txt.asc',
                              '7.txt', '7.txt.asc')))
        # All the data files should still be available.
        self.assertEqual(set(os.listdir(config.updater.cache_partition)),
                         set(('5.txt', '6.txt', '7.txt',
                              '5.txt.asc', '6.txt.asc', '7.txt.asc')))

    @configuration
    def test_cached_files_all_have_bad_signatures(self):
        # All the data files are cached, but the signatures don't match.
        self._setup_server_keyrings()
        touch_build(0)
        # Run the state machine far enough to calculate the winning path.
        state = State()
        state.run_thru('calculate_winner')
        self.assertIsNotNone(state.winner)
        # Let's install all the data files into their final location.  The
        # signature files must be included.
        for path in ('3/4/5.txt', '4/5/6.txt', '5/6/7.txt'):
            data_file = os.path.join(self._serverdir, path)
            shutil.copy(data_file, config.updater.cache_partition)
            # Sign the file with a bogus key.
            dst = os.path.join(config.updater.cache_partition,
                               os.path.basename(data_file))
            sign(dst, 'spare.gpg')
        # All the files will be downloaded.
        requested_downloads = set()
        old_get_files = state.downloader.get_files
        def get_files(downloads, *args, **kws):
            for dst, url in downloads:
                requested_downloads.add(os.path.basename(dst))
            return old_get_files(downloads, *args, **kws)
        state.downloader.get_files = get_files
        state.run_thru('download_files')
        # All the files were re-downloaded.
        self.assertEqual(requested_downloads,
                         set(('5.txt', '5.txt.asc',
                              '6.txt', '6.txt.asc',
                              '7.txt', '7.txt.asc')))
        # All the data files should still be available.
        self.assertEqual(set(os.listdir(config.updater.cache_partition)),
                         set(('5.txt', '6.txt', '7.txt',
                              '5.txt.asc', '6.txt.asc', '7.txt.asc')))

    @configuration
    def test_cached_files_all_have_bad_hashes(self):
        # All the data files are cached, and the signatures match, but the
        # data file hashes are bogus, so they all get downloaded again.
        self._setup_server_keyrings()
        touch_build(0)
        # Run the state machine far enough to calculate the winning path.
        state = State()
        state.run_thru('calculate_winner')
        self.assertIsNotNone(state.winner)
        # Let's install all the data files into their final location.  The
        # signature files must be included.
        for filename in ('5.txt', '6.txt', '7.txt'):
            data_file = os.path.join(config.updater.cache_partition, filename)
            with open(data_file, 'wb') as fp:
                fp.write(b'xxx')
            # Sign the file with the right key.
            dst = os.path.join(config.updater.cache_partition,
                               os.path.basename(data_file))
            sign(dst, 'image-signing.gpg')
        # All the files will be downloaded.
        requested_downloads = set()
        old_get_files = state.downloader.get_files
        def get_files(downloads, *args, **kws):
            for dst, url in downloads:
                requested_downloads.add(os.path.basename(dst))
            return old_get_files(downloads, *args, **kws)
        state.downloader.get_files = get_files
        state.run_thru('download_files')
        # All the files were re-downloaded.
        self.assertEqual(requested_downloads,
                         set(('5.txt', '5.txt.asc',
                              '6.txt', '6.txt.asc',
                              '7.txt', '7.txt.asc')))
        # All the data files should still be available.
        self.assertEqual(set(os.listdir(config.updater.cache_partition)),
                         set(('5.txt', '6.txt', '7.txt',
                              '5.txt.asc', '6.txt.asc', '7.txt.asc')))

    @configuration
    def test_previously_cached_files(self):
        # In this test, we model what happens through the D-Bus API and u/i
        # when a user initiates an upgrade, everything gets downloaded, but
        # they fail to apply and reboot.  Then the D-Bus process times out and
        # exits.  Then the user clicks on Apply and a *new* D-Bus process gets
        # activated with a new state machine.
        #
        # Previously, we'd basically throw everything away and re-download
        # all the files again, and re-calculate the upgrade, but LP: #1217098
        # asks us to do a more bandwidth efficient job of avoiding a
        # re-download of the cached files, assuming all the signatures match
        # and what not.
        #
        # This is harder than it sounds because the state machine, while it
        # can avoid re-downloading data files (note that metadata files like
        # channels.json, index.json, and the blacklist are *always*
        # re-downloaded), a new state machine must try to figure out what the
        # state of the previous invocation was.
        #
        # What the state machine now does first  is look for an
        # `ubuntu_command` file in the cache partition.  If that file exists,
        # it indicates that a previous invocation may have existing state that
        # can be preserved for better efficiency.  We'll make those checks and
        # if it looks okay, we'll short-circuit through the state machine.
        # Otherwise we clean those files out and start from scratch.
        self._setup_server_keyrings()
        state = State()
        state.run_until('reboot')
        self.assertTrue(os.path.exists(
            os.path.join(config.updater.cache_partition, 'ubuntu_command')))
        # Now, to prove that the data files are not re-downloaded with a new
        # state machine, we do two things: we remove the files from the server
        # and we collect the current mtimes (in nanoseconds) of the files in
        # the cache partition.
        for path in ('3/4/5', '4/5/6', '5/6/7'):
            os.remove(os.path.join(self._serverdir, path) + '.txt')
            os.remove(os.path.join(self._serverdir, path) + '.txt.asc')
        mtimes = {}
        for filename in os.listdir(config.updater.cache_partition):
            if filename.endswith('.txt') or filename.endswith('.txt.asc'):
                path = os.path.join(config.updater.cache_partition, filename)
                mtimes[filename] = os.stat(path).st_mtime_ns
        self.assertGreater(len(mtimes), 0)
        # Now create a new state machine, and run until reboot again.  Even
        # though there are no data files on the server, this still completes
        # successfully.
        state = State()
        state.run_until('reboot')
        # Check all the mtimes.
        for filename in os.listdir(config.updater.cache_partition):
            if filename.endswith('.txt') or filename.endswith('.txt.asc'):
                path = os.path.join(config.updater.cache_partition, filename)
                self.assertEqual(mtimes[filename], os.stat(path).st_mtime_ns)

    @configuration
    def test_cleanup_in_download(self):
        # Any residual cache partition files which aren't used in the current
        # update, or which don't validate will be removed before the new files
        # are downloaded.  Except for 'log' and 'last_log'.
        self._setup_server_keyrings()
        touch_build(0)
        # Run the state machine once through downloading the files so we have
        # a bunch of valid cached files.
        State().run_thru('download_files')
        # Now run a new state machine up to just before the step that cleans
        # up the cache partition.
        state = State()
        state.run_until('download_files')
        # Put some files in the cache partition, including the two log files
        # which will be preserved, some dummy files which will be deleted, and
        # a normally preserved cache file which gets invalidated.
        wopen = partial(open, mode='w', encoding='utf-8')
        cache_dir = config.updater.cache_partition
        with wopen(os.path.join(cache_dir, 'log')) as fp:
            print('logger keeper', file=fp)
        with wopen(os.path.join(cache_dir, 'last_log')) as fp:
            print('logger keeper', file=fp)
        with wopen(os.path.join(cache_dir, 'xxx.txt')) as fp:
            print('xxx', file=fp)
        with wopen(os.path.join(cache_dir, 'yyy.txt')) as fp:
            print('yyy', file=fp)
        with open(os.path.join(cache_dir, 'xxx.txt.asc'), 'wb') as fp:
            fp.write(b'xxx')
        with open(os.path.join(cache_dir, 'yyy.txt.asc'), 'wb') as fp:
            fp.write(b'yyy')
        # By filling the asc file with bogus data, we invalidate the data
        # file.
        txt_path = os.path.join(cache_dir, '6.txt')
        asc_path = os.path.join(cache_dir, '6.txt.asc')
        with open(asc_path, 'wb') as fp:
            fp.write(b'zzz')
        # Take the checksum of the 6.txt.asc file so we know it has been
        # replaced.  Get the mtime of the 6.txt file for the same reason (the
        # checksum will still match because the content is the same).
        with open(asc_path, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        mtime = os.stat(txt_path).st_mtime_ns
        state.run_until('reboot')
        with open(asc_path, 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest)
        self.assertNotEqual(mtime, os.stat(txt_path).st_mtime_ns)


class TestKeyringDoubleChecks(ServerTestBase):
    CHANNEL_FILE = 'channels_11.json'
    CHANNEL = 'stable'
    DEVICE = 'nexus7'
    INDEX_FILE = 'index_13.json'
    SIGNING_KEY = 'image-signing.gpg'

    @configuration
    def test_image_master_asc_is_corrupted(self):
        # The state machine will use an existing image master key, unless it
        # is found to be corrupted (i.e. its signature is broken).  If that's
        # the case, it will re-download a new image master.
        setup_keyrings()
        # Re-sign the image master with the wrong key, so as to corrupt its
        # signature via bogus .asc file.
        path = config.gpg.image_master
        sign(path, 'spare.gpg')
        # Prove that the signature is bad.
        with Context(config.gpg.archive_master) as ctx:
            self.assertFalse(ctx.verify(path + '.asc', path))
        # Grab the checksum of the .asc file to prove that it's been
        # downloaded anew.
        with open(path + '.asc', 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # Run the state machine long enough to get the new image master.
        self._setup_server_keyrings()
        State().run_thru('get_blacklist_1')
        # Prove that the signature is good now.
        with Context(config.gpg.archive_master) as ctx:
            self.assertTrue(ctx.verify(path + '.asc', path))
        # We have a new .asc file.
        with open(path + '.asc', 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest())

    @configuration
    def test_image_master_tarxz_is_corrupted(self):
        # As above, except the .tar.xz file is corrupted instead.
        setup_keyrings()
        # Re-sign the image master with the wrong key, so as to corrupt its
        # signature via bogus .asc file.
        path = config.gpg.image_master
        shutil.copy(config.gpg.archive_master, path)
        # Prove that the signature is bad.
        with Context(config.gpg.archive_master) as ctx:
            self.assertFalse(ctx.verify(path + '.asc', path))
        # Grab the checksum of the .tar.xz file to prove that it's been
        # downloaded anew.
        with open(path, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # Run the state machine long enough to get the new image master.
        self._setup_server_keyrings()
        State().run_thru('get_blacklist_1')
        # Prove that the signature is good now.
        with Context(config.gpg.archive_master) as ctx:
            self.assertTrue(ctx.verify(path + '.asc', path))
        # We have a new .asc file.
        with open(path, 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest())

    @configuration
    def test_image_signing_asc_is_corrupted(self):
        # The state machine will use an existing image signing key, unless it
        # is found to be corrupted (i.e. its signature is broken).  If that's
        # the case, it will re-download a new image signing key.
        setup_keyrings()
        # Re-sign the image signing with the wrong key, so as to corrupt its
        # signature via bogus .asc file.
        path = config.gpg.image_signing
        sign(path, 'spare.gpg')
        # Prove that the signature is bad.
        with Context(config.gpg.image_master) as ctx:
            self.assertFalse(ctx.verify(path + '.asc', path))
        # Grab the checksum of the .asc file to prove that it's been
        # downloaded anew.
        with open(path + '.asc', 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # Run the state machine long enough to get the new image master.
        self._setup_server_keyrings()
        State().run_thru('get_channel')
        # Prove that the signature is good now.
        with Context(config.gpg.image_master) as ctx:
            self.assertTrue(ctx.verify(path + '.asc', path))
        # We have a new .asc file.
        with open(path + '.asc', 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest())

    @configuration
    def test_image_signing_tarxz_is_corrupted(self):
        # As above, except the .tar.xz file is corrupted instead.
        setup_keyrings()
        # Re-sign the image master with the wrong key, so as to corrupt its
        # signature via bogus .asc file.
        path = config.gpg.image_signing
        shutil.copy(config.gpg.archive_master, path)
        # Prove that the signature is bad.
        with Context(config.gpg.image_master) as ctx:
            self.assertFalse(ctx.verify(path + '.asc', path))
        # Grab the checksum of the .tar.xz file to prove that it's been
        # downloaded anew.
        with open(path, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # Run the state machine long enough to get the new image master.
        self._setup_server_keyrings()
        State().run_thru('get_channel')
        # Prove that the signature is good now.
        with Context(config.gpg.image_master) as ctx:
            self.assertTrue(ctx.verify(path + '.asc', path))
        # We have a new .asc file.
        with open(path, 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest())

    @configuration
    def test_image_master_is_expired(self):
        # Like above, but the keyring.json has an 'expiry' value that
        # indicates the key has expired.
        expiry = datetime.utcnow() - timedelta(days=10)
        setup_keyrings('image-master', expiry=expiry.timestamp())
        setup_keyrings('archive-master', 'image-signing', 'device-signing')
        # When the state machine re-downloads the image-master, it will change
        # the timestamps on both it and the .asc files.  Grab the mtimes of
        # both now to verify that they've changed later.
        txz_path = config.gpg.image_master
        asc_path = txz_path + '.asc'
        txz_mtime = os.stat(txz_path).st_mtime_ns
        asc_mtime = os.stat(asc_path).st_mtime_ns
        # Additionally, they checksum of the tar.xz file will change because
        # the new one won't have the expiry key in its .json file.
        with open(txz_path, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # Run the state machine long enough to get the new image master.
        self._setup_server_keyrings()
        State().run_thru('get_blacklist_1')
        # We have a new tar.xz file.
        with open(txz_path, 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest())
        self.assertGreater(os.stat(txz_path).st_mtime_ns, txz_mtime)
        self.assertGreater(os.stat(asc_path).st_mtime_ns, asc_mtime)

    @configuration
    def test_image_signing_is_expired(self):
        # Like above, but the keyring.json has an 'expiry' value that
        # indicates the key has expired.
        expiry = datetime.utcnow() - timedelta(days=10)
        setup_keyrings('image-signing', expiry=expiry.timestamp())
        setup_keyrings('archive-master', 'image-master', 'device-signing')
        # When the state machine re-downloads the image-master, it will change
        # the timestamps on both it and the .asc files.  Grab the mtimes of
        # both now to verify that they've changed later.
        txz_path = config.gpg.image_signing
        asc_path = txz_path + '.asc'
        txz_mtime = os.stat(txz_path).st_mtime_ns
        asc_mtime = os.stat(asc_path).st_mtime_ns
        # Additionally, they checksum of the tar.xz file will change because
        # the new one won't have the expiry key in its .json file.
        with open(txz_path, 'rb') as fp:
            checksum = hashlib.md5(fp.read()).digest()
        # Run the state machine long enough to get the new image master.
        self._setup_server_keyrings()
        State().run_thru('get_channel')
        # We have a new tar.xz file.
        with open(txz_path, 'rb') as fp:
            self.assertNotEqual(checksum, hashlib.md5(fp.read()).digest())
        self.assertGreater(os.stat(txz_path).st_mtime_ns, txz_mtime)
        self.assertGreater(os.stat(asc_path).st_mtime_ns, asc_mtime)
