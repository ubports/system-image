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

"""Manage state transitions for updates."""

__all__ = [
    'ChecksumError',
    'State',
    ]


import os
import math
import shutil
import hashlib
import logging

from collections import deque
from contextlib import ExitStack
from functools import partial
from itertools import islice
from operator import itemgetter
from systemimage.candidates import get_candidates, iter_path
from systemimage.channel import Channels
from systemimage.config import config
from systemimage.download import get_files
from systemimage.gpg import Context, SignatureError
from systemimage.helpers import makedirs
from systemimage.index import Index
from systemimage.keyring import KeyringError, get_keyring
from urllib.parse import urljoin


log = logging.getLogger('systemimage')
COMMASPACE = ', '


class ChecksumError(Exception):
    """Exception raised when a file's checksum does not match."""


def _download_feedback(url, dst, bytes_read, size):
    if size:
        digits = math.floor(math.log10(abs(size))) + 1
        fmt = '[{{:{0}d}}/{{:>{0}}}]'.format(digits)
        progress = fmt.format(bytes_read, size)
    else:
        progress = '[{}d bytes]'.format(bytes_read)
    log.debug('download {} {} -> {}', progress, url, dst)


class State:
    def __init__(self, callback=None):
        # Variables which manage state transitions.
        self._next = deque()
        self._next.append(self._get_blacklist_1)
        self._debug_step = 1
        self._callback = (_download_feedback if callback is None else callback)
        # Variables which represent things we've learned.
        self.blacklist = None
        self.channels = None
        self.index = None
        self.candidates = None
        self.winner = None
        self.files = []

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

    def _get_blacklist_1(self):
        """First try to get the blacklist."""
        # If there is no image master key, download one now.  Don't worry if
        # we have an out of date key; that will be handled elsewhere.  The
        # archive master key better be pre-installed (we cannot download it).
        # Let any exceptions in grabbing the image master key percolate up.
        if not os.path.exists(config.gpg.image_master):
            log.info('No image master key found, downloading')
            get_keyring(
                'image-master', 'gpg/image-master.tar.xz', 'archive-master')
        # The only way to know whether there is a blacklist or not is to try
        # to download it.  If it fails, there isn't one.
        url = 'gpg/blacklist.tar.xz'
        try:
            # I think it makes no sense to check the blacklist when we're
            # downloading a blacklist file.
            log.info('Looking for blacklist: {}',
                     urljoin(config.service.https_base, url))
            get_keyring('blacklist', url, 'image-master')
        except SignatureError:
            log.info('No signed blacklist found')
            # The blacklist wasn't signed by the system image master.  Maybe
            # there's a new system image master key?  Let's find out.
            self._next.appendleft(self._get_master_key)
            return
        except FileNotFoundError:
            # There is no blacklist.
            log.info('No blacklist found')
        else:
            # Move the keyring.gpg file to a safe place inside our temporary
            # directory.  It is the responsibility of the code running the
            # state machine to clear out the temporary directory.
            self.blacklist = os.path.join(
                config.system.tempdir, 'blacklist.tar.xz')
            log.info('Local blacklist file: {}', self.blacklist)
        self._next.append(self._get_channel)

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
                     urljoin(config.service.https_base, url))
            get_keyring('blacklist', url, 'image-master')
        except FileNotFoundError:
            log.info('No blacklist found on second attempt')
        else:
            # Move the keyring.gpg file to a safe place inside our temporary
            # directory.  It is the responsibility of the code running the
            # state machine to clear out the temporary directory.
            self.blacklist = os.path.join(
                config.system.tempdir, 'blacklist.tar.xz')
            log.info('Local blacklist file: {}', self.blacklist)
        self._next.append(self._get_channel)

    def _get_channel(self):
        """Get and verify the channels.json file."""
        # If there is no image signing key, download one now.  Don't worry if
        # we have an out of date key; that will be handled elsewhere.  The
        # imaging signing must be signed by the image master key, which we
        # better already have an up-to-date copy of.
        if not os.path.exists(config.gpg.image_signing):
            log.info('No image signing key found, downloading')
            get_keyring(
                'image-signing', 'gpg/image-signing.tar.xz', 'image-master')
        channels_url = urljoin(config.service.https_base, 'channels.json')
        channels_path = os.path.join(config.system.tempdir, 'channels.json')
        asc_url = urljoin(config.service.https_base, 'channels.json.asc')
        asc_path = os.path.join(config.system.tempdir, 'channels.json.asc')
        log.info('Looking for: {}', channels_url)
        with ExitStack() as stack:
            get_files([
                (channels_url, channels_path),
                (asc_url, asc_path),
                ])
            # Once we're done with them, we can remove these files.
            stack.callback(os.remove, channels_path)
            stack.callback(os.remove, asc_path)
            # The channels.json file must be signed with the SYSTEM IMAGE
            # SIGNING key.  There may or may not be a blacklist.
            ctx = stack.enter_context(
                Context(config.gpg.image_signing, blacklist=self.blacklist))
            if not ctx.verify(asc_path, channels_path):
                # The signature on the channels.json file did not match.
                # Maybe there's a new image signing key on the server.  If a
                # new key *is* found, retry the current step.
                self._next.appendleft(self._get_signing_key)
                log.info('channels.json not properly signed')
                return
            # The signature was good.
            log.info('Local channels file: {}', channels_path)
            with open(channels_path, encoding='utf-8') as fp:
                self.channels = Channels.from_json(fp.read())
        # The next step will depend on whether there is a device keyring
        # available or not.  If there is, download and verify it now.
        try:
            device = getattr(
                # This device's channel.
                getattr(self.channels, config.system.channel),
                config.device)
        except AttributeError:
            log.info('no matching channel/device: {}/{}',
                     config.system.channel, config.device)
            # Either our channel or device isn't described in the
            # channels.json file, so there's nothing more to do.
            return
        log.info('found channel/device entry: {}/{}',
                 config.system.channel, config.device)
        keyring = getattr(device, 'keyring', None)
        if keyring:
            self._next.append(partial(self._get_device_keyring, keyring))
        self._next.append(partial(self._get_index, device.index))

    def _get_device_keyring(self, keyring):
        keyring_url = urljoin(config.service.https_base, keyring.path)
        asc_url = urljoin(config.service.https_base, keyring.signature)
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
            # No valid image master key could be found.  Don't chain this
            # exception.
            log.error('No valid imaging master key found')
            raise SignatureError from None
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
            raise SignatureError from None
        # Retry the previous step.
        self._next.appendleft(self._get_channel)

    def _get_index(self, index):
        """Get and verify the index.json file."""
        index_url = urljoin(config.service.https_base, index)
        asc_url = index_url + '.asc'
        index_path = os.path.join(config.system.tempdir, 'index.json')
        asc_path = index_path + '.asc'
        with ExitStack() as stack:
            get_files([
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
            if not ctx.verify(asc_path, index_path):
                raise SignatureError(index_path)
            # The signature was good.
            with open(index_path, encoding='utf-8') as fp:
                self.index = Index.from_json(fp.read())
        self._next.append(self._calculate_winner)

    def _calculate_winner(self):
        """Given an index, calculate the paths and score a winner."""
        # Store these as attributes for debugging and testing.
        self.candidates = get_candidates(self.index, config.build_number)
        self.winner = config.hooks.scorer().choose(self.candidates)
        # If there is no winning upgrade candidate, then there's nothing more
        # to do.  We can skip everything between downloading the files and
        # doing the reboot.
        if len(self.winner) > 0:
            self._next.append(self._download_files)
        else:
            log.info('No update available.')

    def _download_files(self):
        """Download and verify all the winning upgrade path's files."""
        downloads = []
        signatures = []
        sizes = []
        checksums = []
        for image_number, filerec in iter_path(self.winner):
            # Re-pack for arguments to get_files() and to collate the size,
            # signature path, and checksum for the downloadable file.
            dst = os.path.join(
                config.system.tempdir, os.path.basename(filerec.path))
            downloads.append((
                urljoin(config.service.http_base, filerec.path),
                dst,
                ))
            sizes.append(filerec.size)
            self.files.append((dst, (image_number, filerec.order)))
            # Add the signature file, and associate the two.
            asc = os.path.join(
                config.system.tempdir, os.path.basename(filerec.signature))
            downloads.append((
                urljoin(config.service.http_base, filerec.signature),
                asc))
            # There is no size available for the .asc file.
            sizes.append(0)
            self.files.append((asc, (image_number, filerec.order)))
            signatures.append((dst, asc))
            checksums.append((dst, filerec.checksum))
        # If there is a device-signing key, the files can be signed by either
        # that or the image-signing key.
        keyrings = [config.gpg.image_signing]
        if os.path.exists(config.gpg.device_signing):
            keyrings.append(config.gpg.device_signing)
        # Now, download all the files, providing logging feedback on progress.
        get_files(downloads, self._callback, sizes)
        with ExitStack() as stack:
            # Set things up to remove the files if a SignatureError gets
            # raised or if the checksums don't match.  If everything's okay,
            # we'll clear the stack before the context manager exits so none
            # of the files will get removed.
            for url, dst in downloads:
                stack.callback(os.remove, dst)
            # Although we should never get there, if the downloading step
            # fails, clear out the self.files list so there's no possibilty
            # we'll try to move them later.
            stack.callback(setattr, self.files, [])
            # Verify the signatures on all the downloaded files.
            with Context(*keyrings, blacklist=self.blacklist) as ctx:
                for dst, asc in signatures:
                    if not ctx.verify(asc, dst):
                        raise SignatureError(dst)
            # Verify the checksums.
            for dst, checksum in checksums:
                with open(dst, 'rb') as fp:
                    got = hashlib.sha256(fp.read()).hexdigest()
                    if got != checksum:
                        raise ChecksumError(dst, got, checksum)
            # Everything is fine so nothing needs to be cleared.
            stack.pop_all()
        log.info('all files available in {}', config.system.tempdir)
        # Now, copy the files from the temporary directory into the location
        # for the upgrader.
        self._next.append(self._move_files)

    def _move_files(self):
        # The upgrader already has the archive-master, so we don't need to
        # copy it.  The image-master, image-signing, and device-signing (if
        # there is one) keys go to the cache partition.
        cache_dir = config.updater.cache_partition
        data_dir = config.updater.data_partition
        makedirs(cache_dir)
        makedirs(data_dir)
        # Copy the keyring.tar.xz and .asc files.
        shutil.copy(config.gpg.image_master, cache_dir)
        shutil.copy(config.gpg.image_master + '.asc', cache_dir)
        shutil.copy(config.gpg.image_signing, cache_dir)
        shutil.copy(config.gpg.image_signing + '.asc', cache_dir)
        if os.path.exists(config.gpg.device_signing):
            shutil.copy(config.gpg.device_signing, cache_dir)
            shutil.copy(config.gpg.device_signing + '.asc', cache_dir)
        # The blacklist file (if there is one) gets copied to the data
        # partition.
        if self.blacklist is not None:
            shutil.copy(self.blacklist, data_dir)
            shutil.copy(self.blacklist + '.asc', data_dir)
        # Now move all the downloaded data files to the cache.
        for src, (image_number, order) in self.files:
            dst = os.path.join(cache_dir, os.path.basename(src))
            shutil.copy(src, dst)
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
        log.info('preparing to reboot')
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
        with open(command_file, 'w', encoding='utf-8') as fp:
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
        self._next.append(self._reboot)

    def _reboot(self):
        log.info('rebooting')
        config.hooks.reboot().reboot()
        # Nothing more to do.
