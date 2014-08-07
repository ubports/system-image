# Copyright (C) 2014 Canonical Ltd.
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

def main():
    # All imports happen here so that we have the best possible chance of
    # instrumenting all relevant code.
    from systemimage.testing.helpers import Coverage
    Coverage().start()
    # Now run the actual D-Bus service.
    from systemimage.service import main
    return main()


if __name__ == '__main__':
    import sys
    sys.exit(main())
