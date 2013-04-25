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

"""Read the configuration file."""

__all__ = [
    'Configuration',
    ]


import os
import re

# BAW 2013-04-23: If we need something more sophisticated, lazr.config is the
# way to go.  It provides a nice testing infrastruction (pushing/popping of
# configurations), schema definition, and a slew of useful data type
# conversion functions.  For now, we limit the non-stdlib dependencies and
# roll our own.
from configparser import ConfigParser
from datetime import timedelta
from pkg_resources import resource_filename
from resolver.helpers import Bag


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
    """Convert a value string to the equivalent timedeta."""
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


class Configuration:
    def __init__(self):
        # Defaults.
        defaults_ini = resource_filename('resolver.data', 'defaults.ini')
        self.load(defaults_ini)

    def load(self, path):
        parser = ConfigParser()
        parser.read(path)
        self.service = Bag(base=parser['service']['base'])
        self.cache = Bag(
            directory=os.path.expanduser(parser['cache']['directory']),
            lifetime=as_timedelta(parser['cache']['lifetime']),
            )
        self.upgrade = Bag(channel=parser['upgrade']['channel'],
                           device=parser['upgrade']['device'],
                           )
