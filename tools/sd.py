# Debug helper for DBus service.

import dbus

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)

bus = dbus.SystemBus()
service = bus.get_object('com.canonical.SystemImage', '/Service')
iface = dbus.Interface(service, 'com.canonical.SystemImage')

_signals = []

def run(method):
    global _signals
    del _signals[:]
    loop = GLib.MainLoop()
    def uas_cb(*args):
        print('UpdateAvailableStatus:', args)
        _signals.append(args)
        loop.quit()
    def rtr_cb(*args):
        print('ReadyToReboot:', args)
        _signals.append(args)
        loop.quit()
    def uf_cb(*args):
        print('UpdateFailed:', args)
        _signals.append(args)
        loop.quit()
    def c_cb(*args):
        print('Canceled:', args)
        _signals.append(args)
        loop.quit()
    bus.add_signal_receiver(
        uas_cb, signal_name='UpdateAvailableStatus',
        dbus_interface='com.canonical.SystemImage')
    bus.add_signal_receiver(
        rtr_cb, signal_name='ReadyToReboot',
        dbus_interface='com.canonical.SystemImage')
    bus.add_signal_receiver(
        uf_cb, signal_name='UpdateFailed',
        dbus_interface='com.canonical.SystemImage')
    bus.add_signal_receiver(
        c_cb, signal_name='Canceled',
        dbus_interface='com.canonical.SystemImage')
    GLib.timeout_add(100, method)
    GLib.timeout_add_seconds(20, loop.quit)
    loop.run()


print('build number:', iface.BuildNumber())
run(iface.CheckForUpdate)
print('update available?', _signals[0][0])
print('update version:', iface.GetUpdateVersion())
