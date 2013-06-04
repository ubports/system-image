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
    'as_timedelta',
    'as_utcdatetime',
    'atomic',
    'temporary_directory',
    ]


import os
import re
import json
import shutil
import tempfile

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from resolver.bag import Bag


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
    try:
        os.close(fd)
        mode = 'wb' if encoding is None else 'wt'
        with open(temp, mode, encoding=encoding) as fp:
            yield fp
        os.rename(temp, dst)
    finally:
        try:
            os.remove(temp)
        except FileNotFoundError:
            pass


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


def as_utcdatetime(s, utc=True):
    """Convert a string to UTC aware datetime."""
    dt = datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%f')
    if utc:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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
