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

"""Set up logging, both for main script execution and the test suite."""

__all__ = [
    'initialize',
    ]


import logging


def initialize(*, verbosity=0):
    """Initialize the loggers."""
    level = {0: logging.ERROR,
             1: logging.INFO,
             2: logging.DEBUG,
             3: logging.CRITICAL,
             }.get(verbosity, logging.ERROR)
    logging.basicConfig(level=level,
                        datefmt='%b %d %H:%M:%S %Y',
                        format='%(asctime)s (%(process)d) %(message)s')
    log = logging.getLogger('resolver')
    log.setLevel(level)

    # Please be quiet gnupg.
    gnupg_log = logging.getLogger('gnupg')
    gnupg_log.propagate = False
