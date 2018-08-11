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

"""DBus service."""

__all__ = [
    'Loop',
    'Service',
    'log_and_exit',
    ]


import os
import sys
import logging

from datetime import datetime
from dbus.service import Object, method, signal
from functools import wraps
from gi.repository import GLib
from systemimage.api import Mediator
from systemimage.config import config
from systemimage.helpers import last_update_date
from systemimage.settings import Settings
from threading import Lock


EMPTYSTRING = ''
log = logging.getLogger('systemimage')
dbus_log = logging.getLogger('systemimage.dbus')


def log_and_exit(function):
    """Decorator for D-Bus methods to handle tracebacks.

    Put this *above* the @method or @signal decorator.  It will cause
    the exception to be logged and the D-Bus service will exit.
    """
    @wraps(function)
    def wrapper(*args, **kws):
        try:
            dbus_log.info('>>> {}', function.__name__)
            retval = function(*args, **kws)
            dbus_log.info('<<< {}', function.__name__)
            return retval
        except:
            dbus_log.info('!!! {}', function.__name__)
            dbus_log.exception('Error in D-Bus method')
            self = args[0]
            assert isinstance(self, Service), args[0]
            sys.exit(1)
    return wrapper


class Loop:
    """Keep track of the main loop."""

    def __init__(self):
        self._loop = GLib.MainLoop()
        self._quitter = None

    def keepalive(self):
        if self._quitter is not None:
            GLib.source_remove(self._quitter)
            self._quitter = None
        self._quitter = GLib.timeout_add_seconds(
            config.dbus.lifetime.total_seconds(),
            self.quit)

    def quit(self):
        if self._quitter is not None:
            GLib.source_remove(self._quitter)
            self._quitter = None
        self._loop.quit()

    def run(self):
        self._loop.run()


class Service(Object):
    """Main dbus service."""

    def __init__(self, bus, object_path, loop):
        super().__init__(bus, object_path)
        self.loop = loop
        self._api = Mediator(self._progress_callback)
        log.info('Mediator created {}', self._api)
        self._checking = Lock()
        self._downloading = Lock()
        self._update = None
        self._paused = False
        self._applicable = False
        self._failure_count = 0
        self._last_error = ''

    @log_and_exit
    def _check_for_update(self):
        # Asynchronous method call.
        log.info('Enter _check_for_update()')
        self._update = self._api.check_for_update()
        log.info('_check_for_update(): checking lock releasing')
        try:
            self._checking.release()
        except RuntimeError:                        # pragma: no udm
            log.info('_check_for_update(): checking lock already released')
        else:
            log.info('_check_for_update(): checking lock released')
        # Do we have an update and can we auto-download it?
        delayed_download = False
        if self._update.is_available:
            settings = Settings()
            auto = settings.get('auto_download')
            log.info('Update available; auto-download: {}', auto)
            if auto in ('1', '2'):
                # XXX When we have access to the download service, we can
                # check if we're on the wifi (auto == '1').
                delayed_download = True
                GLib.timeout_add(50, self._download)
        # We have a timing issue.  We can't lock the downloading lock here,
        # otherwise when _download() starts running in ~50ms it will think a
        # download is already in progress.  But we want to send the UAS signal
        # here and now, *and* indicate whether the download is about to happen.
        # So just lie for now since in ~50ms the download will begin.
        self.UpdateAvailableStatus(
            self._update.is_available,
            delayed_download,
            self._update.version,
            self._update.size,
            last_update_date(),
            self._update.error)
        # Stop GLib from calling this method again.
        return False

    # 2013-07-25 BAW: should we use the rather underdocumented async_callbacks
    # argument to @method?
    @log_and_exit
    @method('com.canonical.SystemImage')
    def CheckForUpdate(self):
        """Find out whether an update is available.

        This method is used to explicitly check whether an update is
        available, by communicating with the server and calculating an
        upgrade path from the current build number to a later build
        available on the server.

        This method runs asynchronously and thus does not return a result.
        Instead, an `UpdateAvailableStatus` signal is triggered when the check
        completes.  The argument to that signal is a boolean indicating
        whether the update is available or not.
        """
        self.loop.keepalive()
        # Check-and-acquire the lock.
        log.info('CheckForUpdate(): checking lock test and acquire')
        if not self._checking.acquire(blocking=False):
            log.info('CheckForUpdate(): checking lock not acquired')
            # Check is already in progress, so there's nothing more to do.  If
            # there's status available (i.e. we are in the auto-downloading
            # phase of the last CFU), then send the status.
            if self._update is not None:
                self.UpdateAvailableStatus(
                    self._update.is_available,
                    self._downloading.locked(),
                    self._update.version,
                    self._update.size,
                    last_update_date(),
                    "")
            return
        log.info('CheckForUpdate(): checking lock acquired')
        # We've now acquired the lock.  Reset any failure or in-progress
        # state.  Get a new mediator to reset any of its state.
        self._api = Mediator(self._progress_callback)
        log.info('Mediator recreated {}', self._api)
        self._failure_count = 0
        self._last_error = ''
        # Arrange for the actual check to happen in a little while, so that
        # this method can return immediately.
        GLib.timeout_add(50, self._check_for_update)

    #@log_and_exit
    def _progress_callback(self, received, total):
        # Plumb the progress through our own D-Bus API.  Our API is defined as
        # signalling a percentage and an eta.  We can calculate the percentage
        # easily, but the eta is harder.  For now, we just send 0 as the eta.
        percentage = received * 100 // total
        eta = 0
        self.UpdateProgress(percentage, eta)

    @log_and_exit
    def _download(self):
        if self._downloading.locked() and self._paused:
            self._api.resume()
            self._paused = False
            log.info('Download previously paused')
            return
        if (self._downloading.locked()                  # Already in progress.
            or self._update is None                     # Not yet checked.
            or not self._update.is_available            # No update available.
            ):
            log.info('Download already in progress or not available')
            return
        if self._failure_count > 0:
            self._failure_count += 1
            self.UpdateFailed(self._failure_count, self._last_error)
            log.info('Update failures: {}; last error: {}',
                     self._failure_count, self._last_error)
            return
        log.info('_download(): downloading lock entering critical section')
        with self._downloading:
            log.info('Update is downloading')
            try:
                # Always start by sending a UpdateProgress(0, 0).  This is
                # enough to get the u/i's attention.
                self.UpdateProgress(0, 0)
                self._api.download()
            except Exception:
                log.exception('Download failed')
                self._failure_count += 1
                # Set the last error string to the exception's class name.
                exception, value = sys.exc_info()[:2]
                # if there's no meaningful value, omit it.
                value_str = str(value)
                name = exception.__name__
                self._last_error = ('{}'.format(name)
                                    if len(value_str) == 0
                                    else '{}: {}'.format(name, value))
                self.UpdateFailed(self._failure_count, self._last_error)
            else:
                log.info('Update downloaded')
                self.UpdateDownloaded()
                self._failure_count = 0
                self._last_error = ''
                self._applicable = True
        log.info('_download(): downloading lock finished critical section')
        # Stop GLib from calling this method again.
        return False

    @log_and_exit
    @method('com.canonical.SystemImage')
    def DownloadUpdate(self):
        """Download the available update.

        The download may be canceled during this time.
        """
        # Arrange for the update to happen in a little while, so that this
        # method can return immediately.
        self.loop.keepalive()
        GLib.timeout_add(50, self._download)

    @log_and_exit
    @method('com.canonical.SystemImage', out_signature='s')
    def PauseDownload(self):
        """Pause a downloading update."""
        self.loop.keepalive()
        if self._downloading.locked():
            self._api.pause()
            self._paused = True
            error_message = ''
        else:
            error_message = 'not downloading'
        return error_message

    @log_and_exit
    @method('com.canonical.SystemImage', out_signature='s')
    def CancelUpdate(self):
        """Cancel a download."""
        self.loop.keepalive()
        # During the download, this will cause an UpdateFailed signal to be
        # issued, as part of the exception handling in _download().  If we're
        # not downloading, then no signal need be sent.  There's no need to
        # send *another* signal when downloading, because we never will be
        # downloading by the time we get past this next call.
        self._api.cancel()
        # XXX 2013-08-22: If we can't cancel the current download, return the
        # reason in this string.
        return ''

    @log_and_exit
    def _apply_update(self):
        self.loop.keepalive()
        if not self._applicable:
            command_file = os.path.join(
                config.updater.cache_partition, 'ubuntu_command')
            if not os.path.exists(command_file):
                # Not enough has been downloaded to allow for the update to be
                # applied.
                self.Applied(False)
                return
        self._api.apply()
        # This code may or may not run.  On devices for which applying the
        # update requires a system reboot, we're racing against that reboot
        # procedure.
        self._applicable = False
        self.Applied(True)

    @log_and_exit
    @method('com.canonical.SystemImage')
    def ApplyUpdate(self):
        """Apply the update, rebooting the device."""
        GLib.timeout_add(50, self._apply_update)
        return ''

    @log_and_exit
    @method('com.canonical.SystemImage')
    def ForceAllowGSMDownload(self):                # pragma: no curl
        """Force an existing group download to proceed over GSM."""
        log.info('Mediator {}', self._api)
        self._api.allow_gsm()
        return ''

    @log_and_exit
    @method('com.canonical.SystemImage', out_signature='a{ss}')
    def Information(self):
        self.loop.keepalive()
        settings = Settings()
        current_build_number = str(config.build_number)
        version_detail = getattr(config.service, 'version_detail', '')
        response = dict(
            current_build_number=current_build_number,
            device_name=config.device,
            channel_name=config.channel,
            last_update_date=last_update_date(),
            version_detail=version_detail,
            last_check_date=settings.get('last_check_date'),
            )
        if self._update is None:
            response['target_build_number'] = '-1'
            response['target_version_detail'] = ''
        elif not self._update.is_available:
            response['target_build_number'] = current_build_number
            response['target_version_detail'] = version_detail
        else:
            response['target_build_number'] = str(self._update.version)
            response['target_version_detail'] = self._update.version_detail
        return response

    @log_and_exit
    @method('com.canonical.SystemImage', in_signature='ss')
    def SetSetting(self, key, value):
        """Set a key/value setting.

        Some values are special, e.g. min_battery and auto_downloads.
        Implement these special semantics here.
        """
        self.loop.keepalive()
        if key == 'min_battery':
            try:
                as_int = int(value)
            except ValueError:
                return
            if as_int < 0 or as_int > 100:
                return
        if key == 'auto_download':
            try:
                as_int = int(value)
            except ValueError:
                return
            if as_int not in (0, 1, 2):
                return
        settings = Settings()
        old_value = settings.get(key)
        settings.set(key, value)
        if value != old_value:
            # Send the signal.
            self.SettingChanged(key, value)

    @log_and_exit
    @method('com.canonical.SystemImage', in_signature='s', out_signature='s')
    def GetSetting(self, key):
        """Get a setting."""
        self.loop.keepalive()
        return Settings().get(key)

    @log_and_exit
    @method('com.canonical.SystemImage')
    def FactoryReset(self):
        self._api.factory_reset()

    @log_and_exit
    @method('com.canonical.SystemImage')
    def ProductionReset(self):
        self._api.production_reset()

    @log_and_exit
    @method('com.canonical.SystemImage')
    def Exit(self):
        """Quit the daemon immediately."""
        self.loop.quit()

    @log_and_exit
    @method('com.canonical.SystemImage', out_signature='as')
    def GetChannels(self):
        """Get channels from system server."""
        ret = list()
        channels = self._api.get_channels()
        if channels:
            for key in channels:
                if not key["hidden"] and not key["alias"] and not key["redirect"]:
                    ret.append(key["name"])
        log.info('Channels {}', ret)
        return ret

    @log_and_exit
    @method('com.canonical.SystemImage', in_signature='s', out_signature='b')
    def SetChannel(self, channel):
        """Set channel to get updates from"""
        return self._api.set_channel(channel)

    @log_and_exit
    @method('com.canonical.SystemImage', in_signature='i')
    def SetBuild(self, build):
        """Set build to get updates from"""
        self._api.set_build(build)


    @log_and_exit
    @method('com.canonical.SystemImage', out_signature='s')
    def GetChannel(self):
        """Get channel to get updates from"""
        return self._api.get_channel()

    @log_and_exit
    @method('com.canonical.SystemImage', out_signature='i')
    def GetBuild(self):
        """Get build to get updates from"""
        return self._api.get_build()

    @log_and_exit
    @method('com.canonical.SystemImage', out_signature='b')
    def SupportsFirmwareUpdate(self):
        """Check if device supports firmware update"""
        return self._api.supports_firmware_update

    @log_and_exit
    @method('com.canonical.SystemImage', out_signature='s')
    def CheckForFirmwareUpdate(self):
        """Check for firmware update"""
        return self._api.check_for_firmware_update()

    @log_and_exit
    @method('com.canonical.SystemImage', out_signature='s')
    def UpdateFirmware(self):
        """Update firmware"""
        return self._api.update_firmware()

    @log_and_exit
    @method('com.canonical.SystemImage')
    def Reboot(self):
        """Reboot"""
        self._api.reboot()

    @log_and_exit
    @signal('com.canonical.SystemImage', signature='bbsiss')
    def UpdateAvailableStatus(self,
                              is_available, downloading,
                              available_version, update_size,
                              last_update_date,
                              error_reason):
        """Signal sent in response to a CheckForUpdate()."""
        # For .Information()'s last_check_date value.
        iso8601_now = datetime.now().replace(microsecond=0).isoformat(sep=' ')
        Settings().set('last_check_date', iso8601_now)
        log.debug('EMIT UpdateAvailableStatus({}, {}, {}, {}, {}, {})',
                  is_available, downloading, available_version, update_size,
                  last_update_date, repr(error_reason))
        self.loop.keepalive()

    @log_and_exit
    @signal('com.canonical.SystemImage')
    def DownloadStarted(self):
        """The download has started."""
        log.debug('EMIT DownloadStarted()')
        self.loop.keepalive()

    #@log_and_exit
    @signal('com.canonical.SystemImage', signature='id')
    def UpdateProgress(self, percentage, eta):
        """Download progress."""
        log.debug('EMIT UpdateProgress({}, {})', percentage, eta)
        self.loop.keepalive()

    @log_and_exit
    @signal('com.canonical.SystemImage')
    def UpdateDownloaded(self):
        """The update has been successfully downloaded."""
        log.debug('EMIT UpdateDownloaded()')
        self.loop.keepalive()

    @log_and_exit
    @signal('com.canonical.SystemImage', signature='is')
    def UpdateFailed(self, consecutive_failure_count, last_reason):
        """The update failed for some reason."""
        log.debug('EMIT UpdateFailed({}, {})',
                  consecutive_failure_count, repr(last_reason))
        self.loop.keepalive()

    @log_and_exit
    @signal('com.canonical.SystemImage', signature='i')
    def UpdatePaused(self, percentage):
        """The download got paused."""
        log.debug('EMIT UpdatePaused({})', percentage)
        self.loop.keepalive()

    @log_and_exit
    @signal('com.canonical.SystemImage', signature='ss')
    def SettingChanged(self, key, new_value):
        """A setting value has change."""
        log.debug('EMIT SettingChanged({}, {})', repr(key), repr(new_value))
        self.loop.keepalive()

    @log_and_exit
    @signal('com.canonical.SystemImage', signature='b')
    def Applied(self, status):
        """The update has been applied."""
        log.debug('EMIT Applied({})', status)
        self.loop.keepalive()

    @log_and_exit
    @signal('com.canonical.SystemImage', signature='b')
    def Rebooting(self, status):
        """The system is rebooting."""
        # We don't need to keep the loop alive since we're probably just going
        # to shutdown anyway.
        log.debug('EMIT Rebooting({})', status)
