# Copyright (C) 2013-2014 Canonical Ltd.
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
    ]


import os
import sys
import stat
import logging

from contextlib import contextmanager
from systemimage.config import config
from systemimage.helpers import makedirs


DATE_FMT = '%b %d %H:%M:%S %Y'
MSG_FMT = '[{name}] {asctime} ({process:d}) {message}'
LOGFILE_PERMISSIONS = stat.S_IRUSR | stat.S_IWUSR


class FormattingLogRecord(logging.LogRecord):
    def getMessage(self):
        msg = str(self.msg)
        if self.args:
            msg = msg.format(*self.args)
        return msg


def initialize(*, verbosity=0):
    """Initialize the loggers."""
    level = {
        0: logging.ERROR,
        1: logging.INFO,
        2: logging.DEBUG,
        3: logging.CRITICAL,
        }.get(verbosity, logging.ERROR)
    level = min(level, config.system.loglevel)
    # Make sure our library's logging uses {}-style messages.
    logging.setLogRecordFactory(FormattingLogRecord)
    # Now configure the application level logger based on the ini file.
    log = logging.getLogger('systemimage')
    # Make sure the log directory exists.
    makedirs(os.path.dirname(config.system.logfile))
    # touch(1) - but preserve in case file already exists.
    with open(config.system.logfile, 'a', encoding='utf-8'):
        pass
    os.chmod(config.system.logfile, LOGFILE_PERMISSIONS)
    # Our handler will output in UTF-8 using {} style logging.
    handler = logging.FileHandler(config.system.logfile, encoding='utf-8')
    handler.setLevel(level)
    formatter = logging.Formatter(style='{', fmt=MSG_FMT, datefmt=DATE_FMT)
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.propagate = False
    # If we want more verbosity, add a stream handler.
    if verbosity == 0:
        # Set the log level.
        log.setLevel(level)
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    log.addHandler(handler)
    # Set the overall level on the log object to the minimum level.
    log.setLevel(level)
    # Please be quiet gnupg.
    gnupg_log = logging.getLogger('gnupg')
    gnupg_log.propagate = False


@contextmanager
def debug_logging():
    # getEffectiveLevel() is the best we can do, but it's good enough because
    # we always set the level of the logger.
    log = logging.getLogger('systemimage')
    old_level = log.getEffectiveLevel()
    try:
        log.setLevel(logging.DEBUG)
        yield
    finally:
        log.setLevel(old_level)
