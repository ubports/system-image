# Copyright (C) 2013-2016 Canonical Ltd.
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

"""Manage state transitions for updates."""

__all__ = [
    'ChecksumError',
    'State',
    ]


import os
import json
import shutil
import logging
import tarfile

from collections import deque
from contextlib import ExitStack
from datetime import datetime, timezone
from functools import partial
from itertools import islice
from systemimage.candidates import get_candidates, iter_path
from systemimage.channel import Channels
from systemimage.config import config
from systemimage.download import Record, get_download_manager
from systemimage.gpg import Context, SignatureError
from systemimage.helpers import (
    atomic, calculate_signature, makedirs, safe_remove, temporary_directory)
from systemimage.index import Index
from systemimage.keyring import KeyringError, get_keyring
from urllib.parse import urljoin


log = logging.getLogger('systemimage')
COMMASPACE = ', '
COLON = ':'


class ChecksumError(Exception):
    """Exception raised when a file's checksum does not match."""

    def __init__(self, destination, got, checksum):
        super().__init__()
        self.destination = destination
        self.got = got
        self.expected = checksum

    def __str__(self):                              # pragma: no cover
        return 'got:{0.got} != exp:{0.expected}: {0.destination}'.format(self)


def _copy_if_missing(src, dstdir):
    dst_path = os.path.join(dstdir, os.path.basename(src))
    if os.path.exists(src) and not os.path.exists(dst_path):
        shutil.copy(src, dstdir)


def _use_cached(txt, asc, keyrings, checksum=None, blacklist=None):
    if not os.path.exists(txt) or not os.path.exists(asc):
        return False
    with Context(*keyrings, blacklist=blacklist) as ctx:
        if not ctx.verify(asc, txt):
            return False
    if checksum is None:
        return True
    with open(txt, 'rb') as fp:
        got = calculate_signature(fp)
        return got == checksum


def _use_cached_keyring(txz, asc, signing_key):
    if not _use_cached(txz, asc, (signing_key,)):
        return False
    # Do one additional check: unpack the .tar.xz file, grab the keyring.json
    # and if it has an expiry key, make sure that the keyring has not expired.
    with temporary_directory(dir=config.tempdir) as tmp:
        with tarfile.open(txz, 'r:xz') as tf:
            tf.extractall(tmp)
        json_path = os.path.join(tmp, 'keyring.json')
        with open(json_path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
    expiry = data.get('expiry')
    timestamp = datetime.now(tz=timezone.utc).timestamp()
    # We can use this keyring if it never expires, or if the expiration date
    # is some time in the future.
    return expiry is None or expiry > timestamp


class State:
    def __init__(self):
        # Variables which manage state transitions.
        self._next = deque()
        self._debug_step = 1
        self.candidate_filter = None
        self.winner_filter = None
        # Variables which represent things we've learned.
        self.blacklist = None
        self.channels = None
        self.index = None
        self.winner = None
        self.files = []
        self.channel_switch = None
        # Other public attributes.
        self.downloader = get_download_manager()
        self._next.append(self._cleanup)

    def __iter__(self):
        return self

    def _pop(self):
        step = self._next.popleft()
        # step could be a partial or a method.
        name = getattr(step, 'func', step).__name__
        log.debug('-> [{:2}] {}'.format(self._debug_step, name))
        return step, name

    def __next__(self):
        try:
            step, name = self._pop()
            step()
            self._debug_step += 1
        except IndexError:
            # Do not chain the exception.
            raise StopIteration from None
        except:
            log.exception('uncaught exception in state machine')
            raise

    def run_thru(self, stop_after):
        """Total hack to partially run the state machine.

        :param stop_after: Name of method, sans leading underscore to run the
            state machine through.  In other words, the state machine runs
            until the named method completes.
        """
        while True:
            try:
                step, name = self._pop()
            except (StopIteration, IndexError):
                # We're done.
                break
            step()
            self._debug_step += 1
            if name[1:] == stop_after:
                break

    def run_until(self, stop_before):
        """Total hack to partially run the state machine.

        :param stop_before: Name of method, sans leading underscore that the
            state machine is run until the method is reached.  Unlike
            `run_thru()` the named method is not run.
        """
        while True:
            try:
                step, name = self._pop()
            except (StopIteration, IndexError):
                # We're done.
                break
            if name[1:] == stop_before:
                # Stop executing, but not before we push the last state back
                # onto the deque.  Otherwise, resuming the state machine would
                # skip this step.
                self._next.appendleft(step)
                break
            step()
            self._debug_step += 1

    def _cleanup(self):
        """Clean up the destination directories.

        Removes all residual files from the data partition.  We leave the
        cache partition alone because some of those data files may still be
        valid and we want to avoid re-downloading them if possible.
        """
        data_dir = config.updater.data_partition
        # Remove only the blacklist files (and generic keyring files) since
        # these are the only ones that will be downloaded to this location.
        safe_remove(os.path.join(data_dir, 'blacklist.tar.xz'))
        safe_remove(os.path.join(data_dir, 'blacklist.tar.xz.asc'))
        safe_remove(os.path.join(data_dir, 'keyring.tar.xz'))
        safe_remove(os.path.join(data_dir, 'keyring.tar.xz.asc'))
        self._next.append(self._get_blacklist_1)

    def _get_blacklist_1(self):
        """First try to get the blacklist."""
        # If there is no image master key, or if the signature on the key is
        # not valid, download one now.  Don't worry if we have an out of date
        # key; that will be handled elsewhere.  The archive master key better
        # be pre-installed (we cannot download it).  Let any exceptions in
        # grabbing the image master key percolate up.
        image_master = config.gpg.image_master
        if not _use_cached_keyring(image_master, image_master + '.asc',
                                   config.gpg.archive_master):
            log.info('No valid image master key found, downloading')
            get_keyring(
                'image-master', 'gpg/image-master.tar.xz', 'archive-master')
        # The only way to know whether there is a blacklist or not is to try
        # to download it.  If it fails, there isn't one.
        url = 'gpg/blacklist.tar.xz'
        try:
            # I think it makes no sense to check the blacklist when we're
            # downloading a blacklist file.
            log.info('Looking for blacklist: {}'.format(
                     urljoin(config.https_base, url)))
            get_keyring('blacklist', url, 'image-master')
        except SignatureError:
            log.exception('No signed blacklist found')
            # The blacklist wasn't signed by the system image master.  Maybe
            # there's a new system image master key?  Let's find out.
            self._next.appendleft(self._get_master_key)
            return
        except FileNotFoundError:
            # There is no blacklist.
            log.info('No blacklist found')
        else:
            # After successful download, the blacklist.tar.xz will be living
            # in the data partition.
            self.blacklist = os.path.join(
                config.updater.data_partition, 'blacklist.tar.xz')
            log.info('Local blacklist file: {}', self.blacklist)
        # This is the first time we're trying to get the channel.json file.
        # If this fails because signature is invalid, we'll try to download a
        # new image-signing key.  Then we'll call _get_channel() again.
        self._next.append(partial(self._get_channel, 0))

    def _get_blacklist_2(self):
        """Second try to get the blacklist."""
        # Unlike the first attempt, if this one fails with a SignatureError,
        # there's nothing more we can do, so we let those percolate up.  We
        # still catch FileNotFoundErrors because of the small window of
        # opportunity for the blacklist to have been removed between the first
        # attempt and the second.  Since it doesn't cost us much, we might as
        # well be thorough.
        #
        # The first attempt must already have gotten us an image master key if
        # one was missing originally, so don't try that again.
        url = 'gpg/blacklist.tar.xz'
        try:
            log.info('Looking for blacklist again: {}',
                     urljoin(config.https_base, url))
            get_keyring('blacklist', url, 'image-master')
        except FileNotFoundError:
            log.info('No blacklist found on second attempt')
        else:
            # After successful download, the blacklist.tar.xz will be living
            # in the data partition.
            self.blacklist = os.path.join(
                config.updater.data_partition, 'blacklist.tar.xz')
            log.info('Local blacklist file: {}', self.blacklist)
        # See above.
        self._next.append(partial(self._get_channel, 0))

    def _get_channel(self, count):
        """Get and verify the channels.json file."""
        # If there is no image signing key, download one now.  Don't worry if
        # we have an out of date key; that will be handled elsewhere.  The
        # imaging signing must be signed by the image master key, which we
        # better already have an up-to-date copy of.
        image_signing = config.gpg.image_signing
        if not _use_cached_keyring(image_signing, image_signing + '.asc',
                                   config.gpg.image_master):
            log.info('No valid image signing key found, downloading')
            get_keyring(
                'image-signing', 'gpg/image-signing.tar.xz', 'image-master',
                self.blacklist)
        channels_url = urljoin(config.https_base, 'channels.json')
        channels_path = os.path.join(config.tempdir, 'channels.json')
        asc_url = urljoin(config.https_base, 'channels.json.asc')
        asc_path = os.path.join(config.tempdir, 'channels.json.asc')
        log.info('Looking for: {}', channels_url)
        with ExitStack() as stack:
            self.downloader.get_files([
                (channels_url, channels_path),
                (asc_url, asc_path),
                ])
            # Once we're done with them, we can remove these files.
            stack.callback(safe_remove, channels_path)
            stack.callback(safe_remove, asc_path)
            # The channels.json file must be signed with the SYSTEM IMAGE
            # SIGNING key.  There may or may not be a blacklist.
            ctx = stack.enter_context(
                Context(config.gpg.image_signing, blacklist=self.blacklist))
            try:
                ctx.validate(asc_path, channels_path)
            except SignatureError:
                # The signature on the channels.json file did not match.
                # Maybe there's a new image signing key on the server.  If
                # we've already downloaded a new image signing key, then
                # there's nothing more to do but raise an exception.
                # Otherwise, if a new key *is* found, retry the current step.
                if count > 0:
                    raise
                self._next.appendleft(self._get_signing_key)
                log.info('channels.json not properly signed')
                return
            # The signature was good.
            log.info('Local channels file: {}', channels_path)
            with open(channels_path, encoding='utf-8') as fp:
                self.channels = Channels.from_json(fp.read())
        # Locate the index file for the channel/device.
        try:
            channel = self.channels[config.channel]
        except KeyError:
            log.info('no matching channel: {}', config.channel)
            return
        log.info('got channel: {}', config.channel)
        try:
            device = channel.devices[config.device]
        except KeyError:
            log.info('no matching device: {}', config.device)
            return
        log.info('found channel/device entry: {}/{}',
                 config.channel, config.device)
        # The next step will depend on whether there is a device keyring
        # available or not.  If there is, download and verify it now.
        keyring = getattr(device, 'keyring', None)
        if keyring:
            self._next.append(partial(self._get_device_keyring, keyring))
        self._next.append(partial(self._get_index, device.index))

    def _get_device_keyring(self, keyring):
        keyring_url = urljoin(config.https_base, keyring.path)
        asc_url = urljoin(config.https_base, keyring.signature)
        log.info('getting device keyring: {}', keyring_url)
        get_keyring(
            'device-signing', (keyring_url, asc_url), 'image-signing',
            self.blacklist)
        # We don't need to set the next action because it's already been done.

    def _get_master_key(self):
        """Try to get and validate a new image master key.

        If there isn't one, throw a SignatureError.
        """
        try:
            log.info('Getting the image master key')
            # The image signing key must be signed by the archive master.
            get_keyring(
                'image-master', 'gpg/image-master.tar.xz',
                'archive-master', self.blacklist)
        except (FileNotFoundError, SignatureError, KeyringError):
            # No valid image master key could be found.
            log.error('No valid image master key found')
            raise
        # Retry the previous step.
        log.info('Installing new image master key to: {}',
                 config.gpg.image_master)
        self._next.appendleft(self._get_blacklist_2)

    def _get_signing_key(self):
        """Try to get and validate a new image signing key.

        If there isn't one, throw a SignatureError.
        """
        try:
            # The image signing key must be signed by the image master.
            get_keyring(
                'image-signing', 'gpg/image-signing.tar.xz', 'image-master',
                self.blacklist)
        except (FileNotFoundError, SignatureError, KeyringError):
            # No valid image signing key could be found.  Don't chain this
            # exception.
            log.error('No valid image signing key found')
            raise
        # Retry the previous step, but signal to _get_channel() that if the
        # signature fails this time, it's an error.
        self._next.appendleft(partial(self._get_channel, 1))

    def _get_index(self, index):
        """Get and verify the index.json file."""
        index_url = urljoin(config.https_base, index)
        asc_url = index_url + '.asc'
        index_path = os.path.join(config.tempdir, 'index.json')
        asc_path = index_path + '.asc'
        with ExitStack() as stack:
            self.downloader.get_files([
                (index_url, index_path),
                (asc_url, asc_path),
                ])
            stack.callback(os.remove, index_path)
            stack.callback(os.remove, asc_path)
            # Check the signature of the index.json file.  It may be signed by
            # either the device keyring (if one exists) or the image signing
            # key.
            keyrings = [config.gpg.image_signing]
            if os.path.exists(config.gpg.device_signing):
                keyrings.append(config.gpg.device_signing)
            ctx = stack.enter_context(
                Context(*keyrings, blacklist=self.blacklist))
            ctx.validate(asc_path, index_path)
            # The signature was good.
            with open(index_path, encoding='utf-8') as fp:
                self.index = Index.from_json(fp.read())
        self._next.append(self._calculate_winner)

    def _calculate_winner(self):
        """Given an index, calculate the paths and score a winner."""
        # If we were tracking a channel alias, and that channel alias has
        # changed, squash the build number to 0 before calculating the
        # winner.  Otherwise, trust the configured build number.
        channel = self.channels[config.channel]
        # channel_target is the channel we're on based on the alias mapping in
        # our config files.  channel_alias is the alias mapping in the
        # channel.json file, i.e. the channel an update will put us on.
        channel_target = getattr(config.service, 'channel_target', None)
        channel_alias = getattr(channel, 'alias', None)
        if (    channel_alias is None or
                channel_target is None or
                channel_alias == channel_target):
            build_number = config.build_number
        else:
            # This is a channel switch caused by a new alias.  Unless the
            # build number has been explicitly overridden on the command line
            # via --build/-b, use build number 0 to force a full update.
            build_number = (config.build_number
                            if config.build_number_override
                            else 0)
            self.channel_switch = (channel_target, channel_alias)
        candidates = get_candidates(self.index, build_number)
        log.debug('Candidates from build# {}: {}'.format(
            build_number, len(candidates)))
        if self.candidate_filter is not None:
            candidates = self.candidate_filter(candidates)
        self.winner = config.hooks.scorer().choose(
            candidates, (channel_target
                         if channel_alias is None
                         else channel_alias))
        if len(self.winner) == 0:
            log.info('Already up-to-date')
            return
        winning_path = [str(image.version) for image in self.winner]
        log.info('Upgrade path is {}'.format(COLON.join(winning_path)))
        # Now filter the winning path to cap the maximum version number.
        if (self.winner_filter is not None and
                self.winner_filter.maximum_version is not None):
            log.info('Upgrade path capped at version {}'.format(
                self.winner_filter.maximum_version))
            self.winner = self.winner_filter(self.winner)
            if len(self.winner) == 0:
                log.info('Capped upgrade leaves device up-to-date')
                return
        self._next.append(self._download_files)

    def _download_files(self):
        """Download and verify all the winning upgrade path's files."""
        # If there is a device-signing key, the files can be signed by either
        # that or the image-signing key.
        keyrings = [config.gpg.image_signing]
        if os.path.exists(config.gpg.device_signing):
            keyrings.append(config.gpg.device_signing)
        # Now, go through all the file records in the winning upgrade path.
        # If the data file has already been downloaded and it has a valid
        # signature file, then we can save some bandwidth by not downloading
        # it again.
        downloads = []
        signatures = []
        checksums = []
        # For the clean ups below, preserve recovery's log files.
        cache_dir = config.updater.cache_partition
        preserve = set((
            os.path.join(cache_dir, 'log'),
            os.path.join(cache_dir, 'last_log'),
            ))
        for image_number, filerec in iter_path(self.winner):
            # Re-pack for arguments to get_files() and to collate the
            # signature path and checksum for the downloadable file.
            dst = os.path.join(cache_dir, os.path.basename(filerec.path))
            asc = os.path.join(cache_dir, os.path.basename(filerec.signature))
            checksum = filerec.checksum
            self.files.append((dst, (image_number, filerec.order)))
            self.files.append((asc, (image_number, filerec.order)))
            # Check the existence and signature of the file.
            if _use_cached(dst, asc, keyrings, checksum, self.blacklist):
                preserve.add(dst)
                preserve.add(asc)
            else:
                # Add the data file, which has a checksum.
                downloads.append(Record(
                    urljoin(config.http_base, filerec.path),
                    dst, checksum))
                # Add the signature file, which does not have a checksum.
                downloads.append(Record(
                    urljoin(config.http_base, filerec.signature),
                    asc))
                signatures.append((dst, asc))
                checksums.append((dst, checksum))
        # For any files we're about to download, we must make sure that none
        # of the destination file paths exist, otherwise the downloader will
        # throw exceptions.
        for record in downloads:
            safe_remove(record.destination)
        # Also delete cache partition files that we no longer need.
        for filename in os.listdir(cache_dir):
            path = os.path.join(cache_dir, filename)
            if path not in preserve:
                safe_remove(os.path.join(cache_dir, filename))
        # Now, download all missing or ill-signed files, providing logging
        # feedback on progress.  This download can be paused.  The downloader
        # should also signal when the file downloads have started.
        self.downloader.get_files(
            downloads, pausable=True, signal_started=True)
        with ExitStack() as stack:
            # Set things up to remove the files if a SignatureError gets
            # raised or if the checksums don't match.  If everything's okay,
            # we'll clear the stack before the context manager exits so none
            # of the files will get removed.
            for record in downloads:
                stack.callback(os.remove, record.destination)
            # Although we should never get there, if the downloading step
            # fails, clear out the self.files list so there's no possibilty
            # we'll try to move them later.
            stack.callback(setattr, self, 'files', [])
            # Verify the signatures on all the downloaded files.
            with Context(*keyrings, blacklist=self.blacklist) as ctx:
                for dst, asc in signatures:
                    ctx.validate(asc, dst)
            # Verify the checksums.
            for dst, checksum in checksums:
                with open(dst, 'rb') as fp:
                    got = calculate_signature(fp)
                    if got != checksum:
                        raise ChecksumError(dst, got, checksum)
            # Everything is fine so nothing needs to be cleared.
            stack.pop_all()
        log.info('all files available in {}', cache_dir)
        # Now, copy the files from the temporary directory into the location
        # for the upgrader.
        self._next.append(self._move_files)

    def _move_files(self):
        # The upgrader already has the archive-master, so we don't need to
        # copy it.  The image-master, image-signing, and device-signing (if
        # there is one) keys go to the cache partition.  They may already be
        # there if they had to be downloaded, but if not, they're in /var/lib
        # and now need to be copied to the cache partition.  The blacklist
        # keyring, if there is one, should already exist in the data partition.
        cache_dir = config.updater.cache_partition
        makedirs(cache_dir)
        # Copy the keyring.tar.xz and .asc files.
        _copy_if_missing(config.gpg.image_master, cache_dir)
        _copy_if_missing(config.gpg.image_master + '.asc', cache_dir)
        _copy_if_missing(config.gpg.image_signing, cache_dir)
        _copy_if_missing(config.gpg.image_signing + '.asc', cache_dir)
        _copy_if_missing(config.gpg.device_signing, cache_dir)
        _copy_if_missing(config.gpg.device_signing + '.asc', cache_dir)
        # Issue the reboot.
        self._next.append(self._prepare_recovery)

    def _prepare_recovery(self):
        # First we have to create the ubuntu_command file, which will tell the
        # updater which files to apply and in which order.  Right now,
        # self.files contains a sequence of the following contents:
        #
        # [
        #   (file_1,     (image_number, order)),
        #   (file_1.asc, (image_number, order)),
        #   (file_2,     (image_number, order)),
        #   (file_2.asc, (image_number, order)),
        #   ...
        # ]
        #
        # The order of the .asc file is redundant.  Rearrange this sequence so
        # that we have the following:
        #
        # [
        #   ((image_number, order), file_1, file_1.asc),
        #   ((image_number, order), file_2, file_2.asc),
        #   ...
        # ]
        log.info('preparing recovery')
        collated = []
        zipper = zip(
            # items # 0, 2, 4, ...
            islice(self.files, 0, None, 2),
            # items # 1, 3, 5, ...
            islice(self.files, 1, None, 2))
        for (txz, txz_order), (asc, asc_order) in zipper:
            assert txz_order == asc_order, 'Mismatched tar.xz/.asc files'
            collated.append((txz_order, txz, asc))
        ordered = sorted(collated)
        # Open command file and first write the load_keyring commands.
        command_file = os.path.join(
            config.updater.cache_partition, 'ubuntu_command')
        with atomic(command_file) as fp:
            print('load_keyring {0} {0}.asc'.format(
                os.path.basename(config.gpg.image_master)),
                file=fp)
            print('load_keyring {0} {0}.asc'.format(
                os.path.basename(config.gpg.image_signing)),
                file=fp)
            if os.path.exists(config.gpg.device_signing):
                print('load_keyring {0} {0}.asc'.format(
                    os.path.basename(config.gpg.device_signing)),
                    file=fp)
            # If there is a full update, the file system must be formated.
            for image in self.winner:
                if image.type == 'full':
                    print('format system', file=fp)
                    break
            # The filesystem must be mounted.
            print('mount system', file=fp)
            # Now write all the update commands for the tar.xz files.
            for order, txz, asc in ordered:
                print('update {} {}'.format(
                    os.path.basename(txz),
                    os.path.basename(asc)),
                    file=fp)
            # The filesystem must be unmounted.
            print('unmount system', file=fp)
        self._next.append(self._apply)

    def _apply(self):
        log.info('applying')
        config.hooks.apply().apply()
        # Nothing more to do.
