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

"""Set up logging, both for main script execution and the test suite."""

__all__ = [
    'debug_logging',
    'initialize',
    'make_handler',
    ]


import sys
import stat
import logging

from contextlib import contextmanager, suppress
from pathlib import Path
from systemimage.config import config
from systemimage.helpers import DEFAULT_DIRMODE
from xdg.BaseDirectory import xdg_cache_home


DATE_FMT = '%b %d %H:%M:%S %Y'
MSG_FMT = '[{name}] {asctime} ({process:d}) {message}'
LOGFILE_PERMISSIONS = stat.S_IRUSR | stat.S_IWUSR


# We want to support {}-style logging for all systemimage child loggers.  One
# way to do this is with a LogRecord factory, but to play nice with third
# party loggers which might be using %-style, we have to make sure that we use
# the default factory for everything else.
#
# This actually isn't the best way to do this because it still makes a global
# change and we don't know how this will interact with other third party
# loggers.  A marginally better way to do this is to pass class instances to
# the logging calls.  Those instances would have a __str__() method that does
# the .format() conversion.  The problem with that is that it's a bit less
# convenient to make the logging calls because you can't pass strings
# directly.  One such suggestion at <http://tinyurl.com/pjjwjxq> is to import
# the class as __ (i.e. double underscore) so your logging calls would look
# like: log.error(__('Message with {} {}'), foo, bar)

class FormattingLogRecord(logging.LogRecord):
    def __init__(self, name, *args, **kws):
        logger_path = name.split('.')
        self._use_format = (logger_path[0] == 'systemimage')
        super().__init__(name, *args, **kws)

    def getMessage(self):
        if self._use_format:
            msg = str(self.msg)
            if self.args:
                msg = msg.format(*self.args)
            return msg
        else:                                       # pragma: no cover
            return super().getMessage()


def make_handler(path):
    # issue21539 - mkdir(..., exist_ok=True)
    with suppress(FileExistsError):
        path.parent.mkdir(DEFAULT_DIRMODE, parents=True)
    path.touch(LOGFILE_PERMISSIONS)
    # Our handler will output in UTF-8 using {} style logging.
    formatter = logging.Formatter(style='{', fmt=MSG_FMT, datefmt=DATE_FMT)
    handler = logging.FileHandler(bytes(path), encoding='utf-8')
    handler.setFormatter(formatter)
    return handler


def initialize(*, verbosity=0):
    """Initialize the loggers."""
    main, dbus = config.system.loglevel
    for name, loglevel in (('systemimage', main),
                           ('systemimage.dbus', dbus),
                           ('dbus.proxies', dbus)):
        level = {
            0: logging.ERROR,
            1: logging.INFO,
            2: logging.DEBUG,
            3: logging.CRITICAL,
            }.get(verbosity, logging.ERROR)
        level = min(level, loglevel)
        # Make sure our library's logging uses {}-style messages.
        logging.setLogRecordFactory(FormattingLogRecord)
        # Now configure the application level logger based on the ini file.
        log = logging.getLogger(name)
        try:
            handler = make_handler(Path(config.system.logfile))
        except PermissionError:
            handler = make_handler(
                Path(xdg_cache_home) / 'system-image' / 'client.log')
        handler.setLevel(level)
        log.addHandler(handler)
        log.propagate = False
        # If we want more verbosity, add a stream handler.
        if verbosity == 0:                          # pragma: no branch
            # Set the log level.
            log.setLevel(level)
        else:                                       # pragma: no cover
            handler = logging.StreamHandler(stream=sys.stderr)
            handler.setLevel(level)
            formatter = logging.Formatter(
                style='{', fmt=MSG_FMT, datefmt=DATE_FMT)
            handler.setFormatter(formatter)
            log.addHandler(handler)
            # Set the overall level on the log object to the minimum level.
            log.setLevel(level)
    # Please be quiet gnupg.
    gnupg_log = logging.getLogger('gnupg')
    gnupg_log.propagate = False


@contextmanager
def debug_logging(): # pragma: no cover
    # getEffectiveLevel() is the best we can do, but it's good enough because
    # we always set the level of the logger.
    log = logging.getLogger('systemimage')
    old_level = log.getEffectiveLevel()
    try:
        log.setLevel(logging.DEBUG)
        yield
    finally:
        log.setLevel(old_level)
