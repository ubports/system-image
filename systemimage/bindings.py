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

"""Helpers for when the command line script is used as a DBus client."""


__all__ = [
    'DBusClient',
    ]


import dbus

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from importlib import import_module


class ReceivedSignal:
    """Class representing the signal that was received."""

    def __init__(self, *values):
        self.values = values


class UpdateAvailableStatus(ReceivedSignal): pass
class ReadyToReboot(ReceivedSignal): pass
class UpdateFailed(ReceivedSignal): pass
class Canceled(ReceivedSignal): pass


class DBusClient:
    """Python bindings to be used as a DBus client."""

    def __init__(self):
        DBusGMainLoop(set_as_default=True)

        self.bus = dbus.SystemBus()
        service = self.bus.get_object('com.canonical.SystemImage', '/Service')
        self.iface = dbus.Interface(service, 'com.canonical.SystemImage')
        self._myself = import_module('systemimage.bindings')

    def _run(self, method, *signals):
        answers = []
        loop = GLib.MainLoop()
        def callback(*args, **kws):
            signal = kws['member']
            class_ = getattr(self._myself, signal)
            assert issubclass(class_, ReceivedSignal), (
                'Bad signal: {}'.format(signal))
            answers.append(class_(*args))
            loop.quit()
        if len(signals) == 0:
            signals = ('UpdateAvailableStatus', 'ReadyToReboot',
                       'UpdateFailed', 'Canceled')
        for signal in signals:
            self.bus.add_signal_receiver(
                callback, signal_name=signal,
                dbus_interface='com.canonical.SystemImage',
                member_keyword='member')
        GLib.timeout_add(100, method)
        GLib.timeout_add_seconds(120, loop.quit)
        loop.run()
        return answers

    @property
    def build_number(self):
        return self.iface.BuildNumber()

    def check_for_update(self):
        signals = self._run(self.iface.CheckForUpdate, 'UpdateAvailableStatus')
        # That's a sequence of signals, each of which are a single tuple.
        # Unpack the madness.
        assert len(signals) == 1, (
            'Multiple CheckForUpdate signals received: {}'.format(signals))
        assert isinstance(signals[0], UpdateAvailableStatus), (
            'Unexpected signal: {}'.format(signals[0]))
        return bool(signals[0].values[0])

    @property
    def update_size(self):
        return int(self.iface.GetUpdateSize())

    @property
    def update_version(self):
        return int(self.iface.GetUpdateVersion())

    @property
    def update_descriptions(self):
        return self.iface.GetDescriptions()

    def update(self):
        signals = self._run(
            self.iface.GetUpdate, 'UpdateFailed', 'ReadyToReboot')
        assert len(signals) == 1, (
            'Multiple GetUpdate signals received: {}'.format(signals))
        if isinstance(signals[0], ReadyToReboot):
            return True
        elif isinstance(signals[0], UpdateFailed):
            return False
        else:
            raise RuntimeError('Unexpected signal: {}'.format(signals[0]))

    def reboot(self):
        self.iface.Reboot()
