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

from setuptools import find_packages, setup

with open('resolver/version.txt') as fp:
    __version__ = fp.read().strip()


setup(
    name='resolver',
    version=__version__,
    description='Image Based Upgrades',
    author='Barry Warsaw',
    author_email='barry@ubuntu.com',
    license='GNU GPLv3',
    packages=find_packages(),
    include_package_data=True,
    test_suite="resolver.tests",
    )
