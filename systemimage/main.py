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

"""Main script entry point."""


__all__ = [
    'main',
    ]


import sys
import json
import logging
import argparse

from dbus.mainloop.glib import DBusGMainLoop
from pkg_resources import resource_string as resource_bytes
from systemimage.apply import factory_reset, production_reset
from systemimage.candidates import delta_filter, full_filter, version_filter
from systemimage.config import config
from systemimage.helpers import (
    last_update_date, makedirs, phased_percentage, version_detail)
from systemimage.logging import initialize
from systemimage.settings import Settings
from systemimage.state import State
from textwrap import dedent


__version__ = resource_bytes(
    'systemimage', 'version.txt').decode('utf-8').strip()

DEFAULT_CONFIG_D = '/etc/system-image/config.d'
COLON = ':'
LINE_LENGTH = 78


class _DotsProgress:
    def __init__(self):
        self._dot_count = 0

    def callback(self, received, total):
        received = int(received)
        total = int(total)
        sys.stderr.write('.')
        sys.stderr.flush()
        self._dot_count += 1
        show_dots = self._dot_count % LINE_LENGTH == 0
        if show_dots or received >= total:          # pragma: no cover
            sys.stderr.write('\n')
            sys.stderr.flush()


class _LogfileProgress:
    def __init__(self, log):
        self._log = log

    def callback(self, received, total):
        self._log.debug('received: {} of {} bytes', received, total)


def _json_progress(received, total):
    # For use with --progress=json output.  LP: #1423622
    message = json.dumps(dict(
        type='progress',
        now=received,
        total=total))
    sys.stdout.write(message)
    sys.stdout.write('\n')
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        prog='system-image-cli',
        description='Ubuntu System Image Upgrader')
    parser.add_argument('--version',
                        action='version',
                        version='system-image-cli {}'.format(__version__))
    parser.add_argument('-C', '--config',
                        default=DEFAULT_CONFIG_D, action='store',
                        metavar='DIRECTORY',
                        help="""Use the given configuration directory instead
                                of the default""")
    parser.add_argument('-b', '--build',
                        default=None, action='store',
                        help="""Override the current build number just
                                this once""")
    parser.add_argument('-c', '--channel',
                        default=None, action='store',
                        help="""Override the channel just this once.  Use in
                                combination with `--build 0` to switch
                                channels.""")
    parser.add_argument('-d', '--device',
                        default=None, action='store',
                        help='Override the device name just this once')
    parser.add_argument('-f', '--filter',
                        default=None, action='store',
                        help="""Filter the candidate paths to contain only
                                full updates or only delta updates.  The
                                argument to this option must be either `full`
                                or `delta`""")
    parser.add_argument('-m', '--maximage',
                        default=None, type=int,
                        help="""After the winning upgrade path is selected,
                                remove all images with version numbers greater
                                than the given one.  If no images remain in
                                the winning path, the device is considered
                                up-to-date.""")
    parser.add_argument('-g', '--no-apply',
                        default=False, action='store_true',
                        help="""Download (i.e. "get") all the data files and
                                prepare for updating, but don't actually
                                reboot the device into recovery to apply the
                                update""")
    parser.add_argument('-i', '--info',
                        default=False, action='store_true',
                        help="""Show some information about the current
                                device, including the current build number,
                                device name and channel, then exit""")
    parser.add_argument('-n', '--dry-run',
                        default=False, action='store_true',
                        help="""Calculate and print the upgrade path, but do
                                not download or apply it""")
    parser.add_argument('-v', '--verbose',
                        default=0, action='count',
                        help='Increase verbosity')
    parser.add_argument('--progress',
                        default=[], action='append',
                        help="""Add a progress meter.  Available meters are:
                                dots, logfile, and json.  Multiple --progress
                                options are allowed.""")
    parser.add_argument('-p', '--percentage',
                        default=None, action='store',
                        help="""Override the device's phased percentage value
                                during upgrade candidate calculation.""")
    parser.add_argument('--list-channels',
                        default=False, action='store_true',
                        help="""List all available channels, then exit""")
    parser.add_argument('--factory-reset',
                        default=False, action='store_true',
                        help="""Perform a destructive factory reset and
                                reboot.  WARNING: this will wipe all user data
                                on the device!""")
    parser.add_argument('--production-reset',
                        default=False, action='store_true',
                        help="""Perform a destructive production reset
                                (similar to factory reset) and reboot.
                                WARNING: this will wipe all user data
                                on the device!""")
    parser.add_argument('--switch',
                        default=None, action='store', metavar='CHANNEL',
                        help="""Switch to the given channel.  This is
                                equivalent to `-c CHANNEL -b 0`.""")
    # Settings options.
    parser.add_argument('--show-settings',
                        default=False, action='store_true',
                        help="""Show all settings as key=value pairs,
                                then exit""")
    parser.add_argument('--set',
                        default=[], action='append', metavar='KEY=VAL',
                        help="""Set a key and value in the settings, adding
                                the key if it doesn't yet exist, or overriding
                                its value if the key already exists.  Multiple
                                --set arguments can be given.""")
    parser.add_argument('--get',
                        default=[], action='append', metavar='KEY',
                        help="""Get the value for a key.  If the key does not
                                exist, a default value is returned.  Multiple
                                --get arguments can be given.""")
    parser.add_argument('--del',
                        default=[], action='append',
                        metavar='KEY', dest='delete',
                        help="""Delete the key and its value.  It is a no-op
                                if the key does not exist.  Multiple
                                --del arguments can be given.""")
    parser.add_argument('--override-gsm',
                        default=False, action='store_true',
                        help="""When the device is set to only download over
                                WiFi, but is currently on GSM, use this switch
                                to temporarily override the update restriction.
                                This switch has no effect when using the cURL
                                based downloader.""")
    # Hidden system-image-cli only feature for testing purposes.  LP: #1333414
    parser.add_argument('--skip-gpg-verification',
                        default=False, action='store_true',
                        help=argparse.SUPPRESS)

    args = parser.parse_args(sys.argv[1:])
    try:
        config.load(args.config)
    except (TypeError, FileNotFoundError):
        parser.error('\nConfiguration directory not found: {}'.format(
            args.config))
        assert 'parser.error() does not return' # pragma: no cover

    if args.skip_gpg_verification:
        print("""\
WARNING: All GPG signature verifications have been disabled.
Your upgrades are INSECURE.""", file=sys.stderr)
        config.skip_gpg_verification = True

    config.override_gsm = args.override_gsm

    # Perform factory and production resets.
    if args.factory_reset:
        factory_reset()
        # We should never get here, except possibly during the testing
        # process, so just return as normal.
        return 0
    if args.production_reset:
        production_reset()
        # We should never get here, except possibly during the testing
        # process, so just return as normal.
        return 0

    # Handle all settings arguments.  They are mutually exclusive.
    if sum(bool(arg) for arg in
           (args.set, args.get, args.delete, args.show_settings)) > 1:
        parser.error('Cannot mix and match settings arguments')
        assert 'parser.error() does not return' # pragma: no cover

    if args.show_settings:
        rows = sorted(Settings())
        for row in rows:
            print('{}={}'.format(*row))
        return 0
    if args.get:
        settings = Settings()
        for key in args.get:
            print(settings.get(key))
        return 0
    if args.set:
        settings = Settings()
        for keyval in args.set:
            key, val = keyval.split('=', 1)
            settings.set(key, val)
        return 0
    if args.delete:
        settings = Settings()
        for key in args.delete:
            settings.delete(key)
        return 0

    # Sanity check -f/--filter.
    if args.filter is None:
        candidate_filter = None
    elif args.filter == 'full':
        candidate_filter = full_filter
    elif args.filter == 'delta':
        candidate_filter = delta_filter
    else:
        parser.error('Bad filter type: {}'.format(args.filter))
        assert 'parser.error() does not return' # pragma: no cover

    # Create the temporary directory if it doesn't exist.
    makedirs(config.system.tempdir)
    # Initialize the loggers.
    initialize(verbosity=args.verbose)
    log = logging.getLogger('systemimage')
    # We assume the cache_partition already exists, as does the /etc directory
    # (i.e. where the archive master key lives).

    # Command line overrides.  Process --switch first since if both it and
    # -c/-b are given, the latter take precedence.
    if args.switch is not None:
        config.build_number = 0
        config.channel = args.switch
    if args.build is not None:
        try:
            config.build_number = int(args.build)
        except ValueError:
            parser.error(
                '-b/--build requires an integer: {}'.format(args.build))
            assert 'parser.error() does not return' # pragma: no cover
    if args.channel is not None:
        config.channel = args.channel
    if args.device is not None:
        config.device = args.device
    if args.percentage is not None:
        config.phase_override = args.percentage

    if args.info:
        alias = getattr(config.service, 'channel_target', None)
        kws = dict(
            build_number=config.build_number,
            device=config.device,
            channel=config.channel,
            last_update=last_update_date(),
            )
        if alias is None:
            template = """\
                current build number: {build_number}
                device name: {device}
                channel: {channel}
                last update: {last_update}"""
        else:
            template = """\
                current build number: {build_number}
                device name: {device}
                channel: {channel}
                alias: {alias}
                last update: {last_update}"""
            kws['alias'] = alias
        print(dedent(template).format(**kws))
        # If there's additional version details, print this out now too.  We
        # sort the keys in reverse order because we want 'ubuntu' to generally
        # come first.
        details = version_detail()
        for key in sorted(details, reverse=True):
            print('version {}: {}'.format(key, details[key]))
        return 0

    DBusGMainLoop(set_as_default=True)

    if args.list_channels:
        state = State()
        try:
            state.run_thru('get_channel')
        except Exception:
            print('Exception occurred during channel search; '
                  'see log file for details',
                  file=sys.stderr)
            log.exception('system-image-cli exception')
            return 1
        print('Available channels:')
        for key in sorted(state.channels):
            alias = state.channels[key].get('alias')
            if alias is None:
                print('    {}'.format(key))
            else:
                print('    {} (alias for: {})'.format(key, alias))
        return 0

    state = State()
    state.candidate_filter = candidate_filter
    if args.maximage is not None:
        state.winner_filter = version_filter(args.maximage)

    for meter in args.progress:
        if meter == 'dots':
            state.downloader.callbacks.append(_DotsProgress().callback)
        elif meter == 'json':
            state.downloader.callbacks.append(_json_progress)
        elif meter == 'logfile':
            state.downloader.callbacks.append(_LogfileProgress(log).callback)
        else:
            parser.error('Unknown progress meter: {}'.format(meter))
            assert 'parser.error() does not return' # pragma: no cover

    if args.dry_run:
        try:
            state.run_until('download_files')
        except Exception:
            print('Exception occurred during dry-run; '
                  'see log file for details',
                  file=sys.stderr)
            log.exception('system-image-cli exception')
            return 1
        # Say -c <no-such-channel> was given.  This will fail.
        if state.winner is None or len(state.winner) == 0:
            print('Already up-to-date')
        else:
            winning_path = [str(image.version) for image in state.winner]
            kws = dict(path=COLON.join(winning_path))
            target_build = state.winner[-1].version
            if state.channel_switch is None:
                # We're not switching channels due to an alias change.
                template = 'Upgrade path is {path}'
                percentage = phased_percentage(config.channel, target_build)
            else:
                # This upgrade changes the channel that our alias is mapped
                # to, so include that information in the output.
                template = 'Upgrade path is {path} ({from} -> {to})'
                kws['from'], kws['to'] = state.channel_switch
                percentage = phased_percentage(kws['to'], target_build)
            print(template.format(**kws))
            print('Target phase: {}%'.format(percentage))
        return 0
    else:
        # Run the state machine to conclusion.  Suppress all exceptions, but
        # note that the state machine will log them.  If an exception occurs,
        # exit with a non-zero status.
        log.info('running state machine [{}/{}]',
                 config.channel, config.device)
        try:
            if args.no_apply:
                state.run_until('apply')
            else:
                list(state)
        except KeyboardInterrupt:                   # pragma: no cover
            return 0
        except Exception as error:
            print('Exception occurred during update; see log file for details',
                  file=sys.stderr)
            log.exception('system-image-cli exception')
            # This is a little bit of a hack because it's not generalized to
            # all values of --progress.  But OTOH, we always want to log the
            # error, so --progress=logfile is redundant, and --progress=dots
            # doesn't make much sense either.  Just just include some JSON
            # output if --progress=json was specified.
            if 'json' in args.progress:
                print(json.dumps(dict(type='error', msg=str(error))))
            return 1
        else:
            return 0
        finally:
            log.info('state machine finished')


if __name__ == '__main__':                          # pragma: no cover
    sys.exit(main())
