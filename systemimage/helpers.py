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

"""Various and sundry helpers."""

__all__ = [
    'ExtendedEncoder',
    'as_loglevel',
    'as_object',
    'as_timedelta',
    'atomic',
    'last_update_date',
    'makedirs',
    'safe_remove',
    'temporary_directory',
    'version_detail',
    ]


import os
import re
import json
import shutil
import logging
import tempfile

from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from importlib import import_module
from systemimage.bag import Bag


def safe_remove(path):
    """Like os.remove() but don't complain if the file doesn't exist."""
    try:
        os.remove(path)
    except FileNotFoundError:
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
    :raises ValueError: when `value` is not dotted.
    :raises ImportError: if the named module (i.e. up to the right-most dot)
        does not exist.
    :raises AttributeError: if the name after the right-most dot doesn't exist
        in the named module.
    """
    return _Called(value)


def as_timedelta(value):
    """Convert a value string to the equivalent timedelta."""
    # Technically, the regex will match multiple decimal points in the
    # left-hand side, but that's okay because the float/int conversion below
    # will properly complain if there's more than one dot.
    components = sorted(re.findall(r'([\d.]+[smhdw])', value), key=_sortkey)
    # Complain if the components are out of order.
    if ''.join(components) != value:
        raise ValueError
    keywords = dict((interval[0].lower(), interval)
                    for interval in ('weeks', 'days', 'hours',
                                     'minutes', 'seconds'))
    keyword_arguments = {}
    for interval in components:
        if len(interval) == 0:
            raise ValueError
        keyword = keywords.get(interval[-1].lower())
        if keyword is None:
            raise ValueError
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
    level = getattr(logging, value.upper(), None)
    if level is None or not isinstance(level, int):
        raise ValueError
    return level


class ExtendedEncoder(json.JSONEncoder):
    """An extended JSON encoder which knows about other data types."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, timedelta):
            # as_timedelta() does not recognize microseconds, so convert these
            # to floating seconds, but only if there are any seconds.
            if obj.seconds > 0 or obj.microseconds > 0:
                seconds = obj.seconds + obj.microseconds / 1000000.0
                return '{0}d{1}s'.format(obj.days, seconds)
            return '{0}d'.format(obj.days)
        elif isinstance(obj, Bag):
            return obj.original
        return json.JSONEncoder.default(self, obj)


@contextmanager
def temporary_directory(*args, **kws):
    """A context manager that creates a temporary directory.

    The directory and all its contents are deleted when the context manager
    exits.  All positional and keyword arguments are passed to mkdtemp().
    """
    try:
        tempdir = tempfile.mkdtemp(*args, **kws)
        yield tempdir
    finally:
        shutil.rmtree(tempdir)


def makedirs(dir):
    try:
        os.makedirs(dir, exist_ok=True)
    except (FileExistsError, PermissionError):
        pass


def last_update_date():
    """Return the last update date.

    Taken from the mtime of /etc/system-image/channel.ini first, with fallback
    to /etc/ubuntu-build if that file doesn't exist.
    """
    # Avoid circular imports.
    from systemimage.config import config
    channel_ini = os.path.join(
        os.path.dirname(config.config_file), 'channel.ini')
    ubuntu_build = config.system.build_file
    for path in (channel_ini, ubuntu_build):
        try:
            # Local time, since we can't know the timezone.
            timestamp = datetime.fromtimestamp(os.stat(path).st_mtime)
            # Seconds resolution.
            timestamp = timestamp.replace(microsecond=0)
            return str(timestamp)
        except FileNotFoundError:
            pass
    else:
        return 'Unknown'


def version_detail():
    """Return a dictionary of the version details."""
    # Avoid circular imports.
    from systemimage.config import config
    version_details = getattr(config.service, 'version_detail', None)
    if version_details is None:
        return {}
    details = {}
    if version_details is not None:
        for item in version_details.strip().split(','):
            name, equals, version = item.partition('=')
            if equals != '=':
                continue
            details[name] = version
    return details
