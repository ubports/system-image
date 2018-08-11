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

"""DBus API mediator."""


__all__ = [
    'Mediator',
    'Update',
    ]


import logging, json
from subprocess import check_output, CalledProcessError

from systemimage.apply import factory_reset, production_reset
from systemimage.state import State
from systemimage.config import config


log = logging.getLogger('systemimage')


class Update:
    """A representation of the available update."""

    def __init__(self, winners=None, error=''):
        self._winners = [] if winners is None else winners
        self.error = error

    @property
    def is_available(self):
        return len(self._winners) > 0

    @property
    def size(self):
        total_size = 0
        for image in self._winners:
            total_size += sum(filerec.size for filerec in image.files)
        return total_size

    @property
    def descriptions(self):
        return [image.descriptions for image in self._winners]

    @property
    def version(self):
        try:
            return str(self._winners[-1].version)
        except IndexError:
            # No winners.
            return ''

    @property
    def version_detail(self):
        try:
            return self._winners[-1].version_detail
        except IndexError:
            # No winners.
            return ''


class Mediator:
    """This is the DBus API mediator.

    It essentially implements the entire DBus API, but at a level below the
    mechanics of DBus.  Methods of this class are hooked directly into the
    DBus layer to satisfy that interface.
    """

    def __init__(self, callback=None):
        self._state = State()
        self._config = config
        self._update = None
        self._channels = None
        self._callback = callback

    def __repr__(self): # pragma: no cover
        fmt = '<Mediator at 0x{:x} | State at 0x{:x} | Downloader at {}>'
        args = [id(self), id(self._state),
                'None' if self._state.downloader is None
                else '0x{:x}'.format(id(self._state.downloader))
               ]
        return fmt.format(*args)

    def cancel(self):
        self._state.downloader.cancel()

    def pause(self):
        self._state.downloader.pause()

    def resume(self):
        self._state.downloader.resume()

    def check_for_update(self):
        """Is there an update available for this machine?

        :return: Flag indicating whether an update is available or not.
        :rtype: bool
        """
        if self._update is None:
            try:
                self._state.run_until('download_files')
            except Exception as error:
                # Rather than letting this percolate up, eventually reaching
                # the GLib main loop and thus triggering apport, Let's log the
                # error and set the relevant information in the class.
                log.exception('check_for_update failed')
                self._update = Update(error=str(error))
            else:
                self._update = Update(self._state.winner)
                self._channels = list()
                for key in sorted(self._state.channels):
                    self._channels.append(dict(
                        hidden=self._state.channels[key].get('hidden'),
                        alias=self._state.channels[key].get('alias'),
                        redirect=self._state.channels[key].get('redirect'),
                        name=key
                    ))
        return self._update

    def download(self):
        """Download the available update."""
        # We only want callback progress during the actual download.
        old_callbacks = self._state.downloader.callbacks[:]
        try:
            self._state.downloader.callbacks = [self._callback]
            self._state.run_until('apply')
        finally:
            self._state.downloader.callbacks = old_callbacks

    def apply(self):
        """Apply the update."""
        # Transition through all remaining states.
        list(self._state)

    def factory_reset(self):
        factory_reset()

    def production_reset(self):
        production_reset()

    def allow_gsm(self):
        self._state.downloader.allow_gsm()          # pragma: no curl

    def get_channels(self):
        """List channels. This returns output created by check_for_update."""
        return self._channels

    def set_channel(self, channel):
        found = False
        if self._channels:
            for key in self._channels:
                if key["name"] == channel:
                    found = True
                    self._config.channel = channel
                    break
        return found

    def set_build(self, build):
        self._config.build_number = build

    def get_channel(self):
        return self._config.channel

    def get_build(self):
        return self._config.build_number

    @property
    def supports_firmware_update(self):
        """Determines whether the system firmware can be updated using system-image

        :returns: ``True`` if firmware can be updated, ``False`` if it cannot.

        :rtype: bool
        """
        try:
            p = check_output(['afirmflasher', '-jd']).rstrip()
        except CalledProcessError as e:
            log.warning("afirmflasher returned non-zero exit status {}", e.returncode)
            return False
        except OSError as e:
            # afirmflasher isn't installed so this device obviously doesn't support it
            return False

        try:
        	return p.decode('utf8') == "OK"
        except Exception as e:
            log.warning(("Exception occurred while checking whether this device",
                         " supports firmware update."))
            log.exception(e)
            return False

    def check_for_firmware_update(self):
        """Get information about available firmware updates

        :returns: JSON from afirmflasher with available update status
        """

        if not self.supports_firmware_update:
            log.error(("check_for_firmware_update called but device does not ",
                       "support firmware update."))
            return "ERR"

        try:
            p = check_output(['afirmflasher', '-jc']).rstrip()
        except CalledProcessError as e:
            log.warning("afirmflasher returned non-zero exit status {}", e.returncode)
            return "ERR"
        except OSError as e:
            log.exception(e)
            return "ERR"

        try:
            json.loads(p.decode('utf8'))
            return p
        except Exception as e:
            log.warning(("Exception occurred while checking whether this device",
                         " has a firmware update."))
            log.exception(e)
            return "ERR"

    def update_firmware(self):
        """Attempt to update system firmware

        :returns: JSON from afirmflasher with update results
        """

        if not self.supports_firmware_update:
            log.error(("check_for_firmware_update called but device does not ",
                       "support firmware update."))
            return "ERR"

        try:
            p = check_output(['afirmflasher', '-jf']).rstrip()
        except CalledProcessError as e:
            log.warning("afirmflasher returned non-zero exit status {}", e.returncode)
            return "ERR"
        except OSError as e:
            log.exception(e)
            return "ERR"

        try:
            json.loads(p.decode('utf8'))
            return p
        except Exception as e:
            log.warning("Exception occurred while attempting to update firmware")
            log.exception(e)
            return "ERR"

    def reboot(self):
        try:
            check_output(['/sbin/reboot']).rstrip()
        except CalledProcessError:
            log.error("Failed to reboot")
