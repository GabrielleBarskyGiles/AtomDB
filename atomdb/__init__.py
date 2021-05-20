# This file is part of AtomDB.
#
# AtomDB is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# AtomDB is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License
# along with AtomDB. If not, see <http://www.gnu.org/licenses/>.

r"""AtomDB, a database of atomic and ionic properties."""


from os import makedirs

from atomdb.api import *


# __all__ = [ # TODO
# ]


# Ensure the DATAPATH directory exists on the system
# TODO: move this to the LOAD_SPECIES and BUILD_DB functions.
# `makedirs(dir, exists_ok=True)` will make all subdirectories recursively, or do nothing.
os.makedirs(DATAPATH, exists_ok=True)