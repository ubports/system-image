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

"""DBus API mediator."""


__all__ = [
    'Mediator',
    ]


from systemimage.state import State


class Mediator:
    """This is the DBus API mediator.

    It essentially implements the entire DBus API, but at a level below the
    mechanics of DBus.  Methods of this class are hooked directly into the
    DBus layer to satisfy that interface.
    """

    def __init__(self):
        self._state = State()

    def check_for_update(self):
        """Is there an update available for this machine?

        :return: Flag indicating whether an update is available or not.
        :rtype: bool
        """
        self._state.run_thru('calculate_winner')
        return bool(self._state.winner)
