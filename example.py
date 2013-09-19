import os
import sys
import shutil

from dbus import SessionBus, Interface, Dictionary
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)

DOWNLOADS = [
    # File 1.
    ## ('http://www.python.org/ftp/python/3.4.0/Python-3.4.0a2.tgz',
    ##  '/tmp/Python-3.4.0a2.tgz',
    ##  ''),
    ##  #'e6e81242a32e6f63d224254d24edbd2f'),
    ## # File 2
    ## ('http://www.python.org/ftp/python/3.4.0/Python-3.4.0a2.tar.xz',
    ##  '/tmp/Python-3.4.0a2.tar.xz',
    ##  ''),
    ##  #'36c941d1466730a70d0ae92442cc3fcf'),
    # File 3
    ('http://system-image.ubuntu.com/channels.json',
     '/tmp/channels.json',
     ''),
    # File 4
    ('http://system-image.ubuntu.com/daily-proposed/grouper/index.json',
     '/tmp/index.json',
     ''),
    # File 5
    ('http://system-image.ubuntu.com/gpg/archive-master.tar.xz.asc',
     '/tmp/archive-master.tar.xz.asc',
     ''),
    ]


class Reactor:
    """A reactor base class for DBus signals."""

    def __init__(self, bus, iface=None):
        self._bus = bus
        self._iface = iface
        self._loop = None
        self._quitters = []
        self._signal_matches = []
        self.timeout = 60

    def _handle_signal(self, *args, **kws):
        signal = kws.pop('member')
        path = kws.pop('path')
        method = getattr(self, '_do_' + signal, None)
        if method is None:
            # See if there's a default catch all.
            method = getattr(self, '_default', None)
        if method is not None:
            method(signal, path, *args, **kws)

    def react_to(self, signal):
        if self._iface is None:
            signal_match = self._bus.add_signal_receiver(
                self._handle_signal, signal_name=signal,
                member_keyword='member',
                path_keyword='path')
        else:
            signal_match = self._iface.connect_to_signal(
                signal, self._handle_signal,
                member_keyword='member',
                path_keyword='path')
        self._signal_matches.append(signal_match)

    def schedule(self, method, milliseconds=50):
        GLib.timeout_add(milliseconds, method)

    def run(self):
        self._loop = GLib.MainLoop()
        source_id = GLib.timeout_add_seconds(self.timeout, self.quit)
        self._quitters.append(source_id)
        self._loop.run()

    def quit(self):
        self._loop.quit()
        for match in self._signal_matches:
            match.remove()
        del self._signal_matches[:]
        for source_id in self._quitters:
            GLib.source_remove(source_id)
        del self._quitters[:]


class DownloadReactor(Reactor):
    def __init__(self, movers, bus, iface=None):
        super().__init__(bus, iface)
        self._movers = movers
        self.received_bytes = 0
        self.react_to('canceled')
        self.react_to('error')
        self.react_to('finished')
        self.react_to('paused')
        self.react_to('progress')
        self.react_to('resumed')
        self.react_to('started')

    def _do_finished(self, signal, path, local_paths):
        print('FINISHED', file=sys.stderr)
        for actual_path in local_paths:
            head, tail = os.path.split(actual_path)
            real_destination = self._movers.pop(tail)
            # We can't guarantee that both paths are on the same device, so
            # use shutil.move() instead of os.rename().
            shutil.move(actual_path, real_destination)
        self.quit()

    def _do_progress(self, signal, path, received, total):
        self.received_bytes += received
        print('PROGRESS:', received, 'of', total, file=sys.stderr)

    def _default(self, *args, **kws):
        print('SIGNAL:', args, kws, file=sys.stderr)


if __name__ == '__main__':
    b = SessionBus()
    m = b.get_object('com.canonical.applications.Downloader', '/')
    i = Interface(m, 'com.canonical.applications.DownloaderManager')

    # LP: #1224641
    movers = {}
    for url, dst, md5sum in DOWNLOADS:
        head, tail = os.path.split(url)
        movers[tail] = dst

    path = i.createDownloadGroup(
        DOWNLOADS, '', #'md5',
        # Don't allow GSM,
        False,
        # https://bugs.freedesktop.org/show_bug.cgi?id=55594
        Dictionary(signature='sv'),
        {'User-Agent': 'Ubuntu System Image Upgrade Client; Build 3'},
        )

    dl = b.get_object('com.canonical.applications.Downloader', path)
    dl_i = Interface(dl, 'com.canonical.applications.GroupDownload')

    reactor = DownloadReactor(movers, b, dl_i)
    reactor.schedule(dl_i.start)
    reactor.run()
