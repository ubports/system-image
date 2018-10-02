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

"""Various and sundry helpers."""

__all__ = [
    'DEFAULT_DIRMODE',
    'MiB',
    'as_loglevel',
    'as_object',
    'as_port',
    'as_stripped',
    'as_timedelta',
    'atomic',
    'calculate_signature',
    'last_update_date',
    'makedirs',
    'phased_percentage',
    'safe_remove',
    'temporary_directory',
    'version_detail',
    ]


import os
import re
import random
import shutil
import logging
import tempfile

from contextlib import ExitStack, contextmanager, suppress
from datetime import datetime, timedelta
from hashlib import sha256
from importlib import import_module


UNIQUE_MACHINE_ID_FILES = ['/var/lib/dbus/machine-id', '/etc/machine-id']
LAST_UPDATE_FILE = '/userdata/.last_update'
TIMEKEEPER_OFFSET_FILE = '/data/time/timekeep'
DEFAULT_DIRMODE = 0o02700
MiB = 1 << 20
EMPTYSTRING = ''
NO_PORT = object()


def calculate_signature(fp, hash_class=None):
    """Calculate the hex digest hash signature for a file stream.

    :param fp: The open file object.  This function will read the entire
        contents of the file, leaving the file pointer at the end.  It is the
        responsibility of the caller to both open and close the file.
    :type fp: File-like object with `.read(count)` method.
    :param hash_class: The hash class to use.  Defaults to `hashlib.sha256`.
    :type hash_class: Object having both `.update(bytes)` and `.hexdigest()`
        methods.
    :return: The hex digest of the contents of the file.
    :rtype: str
    """
    checksum = (sha256 if hash_class is None else hash_class)()
    while True:
        chunk = fp.read(MiB)
        if not chunk:
            break
        checksum.update(chunk)
    return checksum.hexdigest()


def safe_remove(path):
    """Like os.remove() but don't complain if the file doesn't exist."""
    try:
        os.remove(path)
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        pass


@contextmanager
def atomic(dst, encoding='utf-8'):
    """Open a temporary file for writing using the given encoding.

    The context manager returns an open file object, into which you can write
    text or bytes depending on the encoding it was opened with.  Upon exit,
    the temporary file is moved atomically to the destination.  If an
    exception occurs, the temporary file is removed.

    :param dst: The path name of the target file.
    :param encoding: The encoding to use for the open file.  If None, then
        file is opened in binary mode.
    """
    directory = os.path.dirname(dst)
    fd, temp = tempfile.mkstemp(dir=directory)
    with ExitStack() as stack:
        stack.callback(safe_remove, temp)
        os.close(fd)
        mode = 'wb' if encoding is None else 'wt'
        with open(temp, mode, encoding=encoding) as fp:
            yield fp
        os.rename(temp, dst)


# This is stolen directly out of lazr.config.  We can do that since we own
# both code bases. :)
def _sortkey(item):
    """Return a value that sorted(..., key=_sortkey) can use."""
    order = dict(
        w=0,    # weeks
        d=1,    # days
        h=2,    # hours
        m=3,    # minutes
        s=4,    # seconds
        )
    return order.get(item[-1])


class _Called:
    # Defer importing named object until it's actually called.  This should
    # reduce the instances of circular imports.
    def __init__(self, path):
        self._path, dot, self._name = path.rpartition('.')
        if dot != '.':
            raise ValueError

    def _dig(self):
        module = import_module(self._path)
        return getattr(module, self._name)

    def __call__(self, *args, **kws):
        return self._dig()(*args, **kws)

    def __eq__(self, other):
        # Let class equality (and in-equality) work.
        myself = self._dig()
        return myself == other

    def __ne__(self, other):
        return not self.__eq__(other)


def as_object(value):
    """Convert a Python dotted-path specification to an object.

    :param value: A dotted-path specification,
        e.g. the string `systemimage.scores.WeightedScorer`
    :return: A proxy object that when called, performs the import and calls
        the underyling object.
    :raises ValueError: when `value` is not dotted.
    """
    return _Called(value)


def as_timedelta(value):
    """Convert a value string to the equivalent timedelta."""
    # Technically, the regex will match multiple decimal points in the
    # left-hand side, but that's okay because the float/int conversion below
    # will properly complain if there's more than one dot.
    components = sorted(re.findall(r'([\d.]+[smhdw])', value), key=_sortkey)
    # Complain if the components are out of order.
    if EMPTYSTRING.join(components) != value:
        raise ValueError
    keywords = dict((interval[0].lower(), interval)
                    for interval in ('weeks', 'days', 'hours',
                                     'minutes', 'seconds'))
    keyword_arguments = {}
    for interval in components:
        assert len(interval) > 0, 'Unexpected value: {}'.format(interval)
        keyword = keywords[interval[-1].lower()]
        if keyword in keyword_arguments:
            raise ValueError
        if '.' in interval[:-1]:
            converted = float(interval[:-1])
        else:
            converted = int(interval[:-1])
        keyword_arguments[keyword] = converted
    if len(keyword_arguments) == 0:
        raise ValueError
    return timedelta(**keyword_arguments)


def as_loglevel(value):
    # The value can now be a single name, like "info" or two names separated
    # by a colon, such as "info:debug".  In the later case, the second name is
    # used to initialize the systemimage.dbus logger.  In the former case, the
    # dbus logger defaults to 'error'.
    main, colon, dbus = value.upper().partition(':')
    if len(dbus) == 0:
        dbus = 'ERROR'
    main_level = getattr(logging, main, None)
    if main_level is None or not isinstance(main_level, int):
        raise ValueError(value)
    dbus_level = getattr(logging, dbus, None)
    if dbus_level is None or not isinstance(dbus_level, int):
        raise ValueError(value)
    return main_level, dbus_level


def as_port(value):
    if value.lower() in ('disabled', 'disable'):
        return NO_PORT
    result = int(value)
    if result < 0:
        raise ValueError(value)
    return result


def as_stripped(value):
    return value.strip()


@contextmanager
def temporary_directory(*args, **kws):
    """A context manager that creates a temporary directory.

    The directory and all its contents are deleted when the context manager
    exits.  All positional and keyword arguments are passed to mkdtemp().
    """
    tempdir = tempfile.mkdtemp(*args, **kws)
    os.chmod(tempdir, kws.get('mode', DEFAULT_DIRMODE))
    try:
        yield tempdir
    finally:
        try:
            shutil.rmtree(tempdir)
        except FileNotFoundError:
            pass


def makedirs(dir, mode=DEFAULT_DIRMODE):
    os.makedirs(dir, mode=mode, exist_ok=True)


def get_android_offset():
    """Return the number of seconds delta between the hardware clock and now.

    Some Android devices have a read-only hardware clock, so we store the number
    of seconds between the read-only clock and the current time in a file, then
    read that file at boot time to determine what the current time actually is.
    In our Android recoveries, we don't really care what the current time is
    and don't take this step, so the mtime of our "last-update" file is
    incorrect.  This method reads and returns the number of seconds stored in
    the offset file.

    If the time offset file doesn't open or contains non-int data, this method
    returns 0.
    """
    log = logging.getLogger('systemimage')
    try:
        with open(TIMEKEEPER_OFFSET_FILE, 'rt') as f:
            time_offset = int(f.readline())
            log.info("Hardware clock offset is {}".format(time_offset))
            return time_offset
    except (OSError, IOError):
        # We couldn't open the offset file, so there's no offset on this platform
        log.info("Couldn't open time offset file, assuming zero offset.")
        return 0
    except (ValueError):
        # The value in the file doesn't cast to an int
        log.info("Found garbage in time offset file, assuming zero offset.")
        return 0


def last_update_date():
    """Return the last update date.

    If /userdata/.last_update exists, we use this file's mtime.  If it doesn't
    exist, then we use the latest mtime of any of the files in
    /etc/system-image/config.d/*.ini (or whatever directory was given with the
    -C/--config option).  We also use the Android offset, if it is available,
    to get a more correct date.
    """
    # Avoid circular imports.
    from systemimage.config import config
    try:
        timestamp_raw = os.stat(LAST_UPDATE_FILE).st_mtime
        timestamp = datetime.fromtimestamp(timestamp_raw)
    except (FileNotFoundError, PermissionError):
        # We fall back to the latest mtime of the config.d/*.ini files.  For
        # robustness, watch out for two possibilities: the config file could
        # have been deleted after the system started up (thus making
        # config.ini_files include nonexistent files), and the ini file could
        # be a dangling symlink.  For the latter, use lstat().
        timestamps = []
        for path in config.ini_files:
            with suppress(FileNotFoundError):
                timestamps.append(
                    datetime.fromtimestamp(path.lstat().st_mtime))
        if len(timestamps) == 0:
            return 'Unknown'
        timestamp = sorted(timestamps)[-1]
    delta = timedelta(seconds=get_android_offset())
    return str(timestamp.replace(microsecond=0) + delta)


def version_detail(details_string=None):
    """Return a dictionary of the version details."""
    # Avoid circular imports.
    if details_string is None:
        from systemimage.config import config
        details_string = getattr(config.service, 'version_detail', None)
    if details_string is None:
        return {}
    details = {}
    for item in details_string.strip().split(','):
        name, equals, version = item.partition('=')
        if equals != '=':
            continue
        details[name] = version
    return details


def phased_percentage(channel, target):
    # Avoid circular imports.
    from systemimage.config import config
    if config.phase_override is not None:
        return config.phase_override
    for path in UNIQUE_MACHINE_ID_FILES:
        try:
            with open(path, 'r', encoding='utf-8') as fp:
                machine_id = fp.read().strip()
                break                               # pragma: no branch
        except FileNotFoundError:
            pass
    else:
        raise RuntimeError('No machine-id file found')
    r = random.Random()
    r.seed('{}.{}.{}'.format(channel, target, machine_id))
    return r.randint(0, 100)
