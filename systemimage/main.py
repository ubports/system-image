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

"""Main script entry point."""


__all__ = [
    'main',
    ]


import os
import sys
import logging
import argparse

from dbus.mainloop.glib import DBusGMainLoop
from pkg_resources import resource_string as resource_bytes
from systemimage.bindings import DBusClient
from systemimage.candidates import delta_filter, full_filter
from systemimage.config import config
from systemimage.helpers import last_update_date, makedirs, version_detail
from systemimage.logging import initialize
from systemimage.state import State
from textwrap import dedent


__version__ = resource_bytes(
    'systemimage', 'version.txt').decode('utf-8').strip()

DEFAULT_CONFIG_FILE = '/etc/system-image/client.ini'
COLON = ':'


def main():
    global config
    parser = argparse.ArgumentParser(
        prog='system-image-cli',
        description='Ubuntu System Image Upgrader')
    parser.add_argument('--version',
                        action='version',
                        version='system-image-cli {}'.format(__version__))
    parser.add_argument('-C', '--config',
                        default=DEFAULT_CONFIG_FILE, action='store',
                        metavar='FILE',
                        help="""Use the given configuration file instead of
                                the default""")
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
    parser.add_argument('--dbus',
                        default=False, action='store_true',
                        help='Run in D-Bus client mode.')
    parser.add_argument('-f', '--filter',
                        default=None, action='store',
                        help="""Filter the candidate paths to contain only
                                full updates or only delta updates.  The
                                argument to this option must be either `full`
                                or `delta`""")
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

    args = parser.parse_args(sys.argv[1:])
    try:
        config.load(args.config)
    except FileNotFoundError as error:
        parser.error('\nConfiguration file not found: {}'.format(error))
        assert 'parser.error() does not return'
    # Load the optional channel.ini file, which must live next to the
    # configuration file.  It's okay if this file does not exist.
    channel_ini = os.path.join(os.path.dirname(args.config), 'channel.ini')
    try:
        config.load(channel_ini, override=True)
    except FileNotFoundError:
        pass

    # Sanity check -f/--filter.
    if args.filter is None:
        candidate_filter = None
    elif args.filter == 'full':
        candidate_filter = full_filter
    elif args.filter == 'delta':
        candidate_filter = delta_filter
    else:
        parser.error('Bad filter type: {}'.format(args.filter))
        assert 'parser.error() does not return'

    # Create the temporary directory if it doesn't exist.
    makedirs(config.system.tempdir)
    # Initialize the loggers.
    initialize(verbosity=args.verbose)
    log = logging.getLogger('systemimage')
    # We assume the cache_partition already exists, as does the /etc directory
    # (i.e. where the archive master key lives).

    # Command line overrides.
    if args.build is not None:
        try:
            config.build_number = int(args.build)
        except ValueError:
            parser.error(
                '-b/--build requires an integer: {}'.format(args.build))
            assert 'parser.error() does not return'
    if args.channel is not None:
        config.channel = args.channel
    if args.device is not None:
        config.device = args.device

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

    # We can either run the API directly or through DBus.
    if args.dbus:
        client = DBusClient()
        client.check_for_update()
        if not client.is_available:
            log.info('No update is available')
            return 0
        if not client.downloaded:
            log.info('No update was downloaded')
            return 1
        if client.failed:
            log.info('Update failed')
            return 2
        client.reboot()
        # We probably won't get here..
        return 0

    # When verbosity is at 1, logging every progress signal from
    # ubuntu-download-manager would be way too noisy.  OTOH, not printing
    # anything leads some folks to think the process is just hung, since it
    # can take a long time to download all the data files.  As a compromise,
    # we'll output some dots to stderr at verbosity 1, but we won't log these
    # dots since they would just be noise.  This doesn't have to be perfect.
    if args.verbose == 1:
        dot_count = 0
        def callback(received, total):
            nonlocal dot_count
            sys.stderr.write('.')
            sys.stderr.flush()
            dot_count += 1
            if dot_count % 78 == 0 or received >= total:
                sys.stderr.write('\n')
                sys.stderr.flush()
    else:
        def callback(received, total):
            log.debug('received: {} of {} bytes', received, total)

    DBusGMainLoop(set_as_default=True)
    state = State(candidate_filter=candidate_filter)
    state.downloader.callback = callback
    if args.dry_run:
        state.run_until('download_files')
        # Say -c <no-such-channel> was given.  This will fail.
        if state.winner is None or len(state.winner) == 0:
            print('Already up-to-date')
        else:
            winning_path = [str(image.version) for image in state.winner]
            kws = dict(path=COLON.join(winning_path))
            if state.channel_switch is None:
                # We're not switching channels due to an alias change.
                template = 'Upgrade path is {path}'
            else:
                # This upgrade changes the channel that our alias is mapped
                # to, so include that information in the output.
                template = 'Upgrade path is {path} ({from} -> {to})'
                kws['from'], kws['to'] = state.channel_switch
            print(template.format(**kws))
        return
    else:
        # Run the state machine to conclusion.  Suppress all exceptions, but
        # note that the state machine will log them.  If an exception occurs,
        # exit with a non-zero status.
        log.info('running state machine [{}/{}]',
                 config.channel, config.device)
        try:
            list(state)
        except KeyboardInterrupt:
            return 0
        except:
            log.exception('system-image-cli exception')
            return 1
        else:
            return 0


if __name__ == '__main__':
    sys.exit(main())
