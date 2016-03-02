# Copyright (C) 2014-2016 Canonical Ltd.
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

"""DBus service testing pre-load module.

This is arranged so that the test suite can enable code coverage data
collection as early as possible in the private bus D-Bus activated processes.
"""

import os

# Set this environment variable if the controller won't start.  There's no
# other good way to get debugging information about the D-Bus activated
# process, since their stderr just seems to get lost.
if os.environ.get('SYSTEMIMAGE_DEBUG_DBUS_ACTIVATION'):
    import sys
    sys.stderr = open('/tmp/debug.log', 'a', encoding='utf-8')


# It's okay if this module isn't available.
try:
    from coverage.control import coverage as _Coverage
except ImportError:
    _Coverage = None


def main():
    # Enable code coverage.
    ini_file = os.environ.get('COVERAGE_PROCESS_START')
    if _Coverage is not None and ini_file is not None:
        coverage =_Coverage(config_file=ini_file, auto_data=True)
        # Stolen from coverage.process_startup()
        coverage.erase()
        coverage.start()
        coverage._warn_no_data = False
        coverage._warn_unimported_source = False
    # All systemimage imports happen here so that we have the best possible
    # chance of instrumenting all relevant code.
    from systemimage.service import main as real_main
    # Now run the actual D-Bus service.
    return real_main()


if __name__ == '__main__':
    import sys
    sys.exit(main())
