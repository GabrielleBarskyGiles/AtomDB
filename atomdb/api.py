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


from dataclasses import dataclass, field, asdict

from importlib import import_module

from json import JSONEncoder, dumps

from os import environ, makedirs

from os.path import dirname, join

from sys import platform

from msgpack import Packer, Unpacker

from numpy import ndarray, frombuffer, exp, log

from scipy.interpolate import interp1d

from csv import reader

from .units import angstrom, amu


__all__ = [
    "DEFAULT_DATASET",
    "DEFAULT_DATAPATH",
    "Species",
    "load",
    "compile",
    "datafile",
    "element_number",
    "element_symbol",
    "get_element_data",
]


DEFAULT_DATASET = "hci"
r"""Default dataset to query."""


DEFAULT_DATAPATH = environ.get("ATOMDB_DATAPATH", join(dirname(__file__), "datasets/"))
r"""The path for raw and compiled AtomDB data files."""


ELEMENTS = (
    # fmt: off
    "\0", "H",  "He", "Li", "Be", "B",  "C",  "N",  "O",  "F",  "Ne", "Na",
    "Mg", "Al", "Si", "P",  "S",  "Cl", "Ar", "K",  "Ca", "Sc", "Ti", "V",
    "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br",
    "Kr", "Rb", "Sr", "Y",  "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag",
    "Cd", "In", "Sn", "Sb", "Te", "I",  "Xe", "Cs", "Ba", "La", "Ce", "Pr",
    "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
    "Hf", "Ta", "W",  "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
    "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U",  "Np", "Pu", "Am",
    "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh",
    "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
    # fmt: on
)
r"""Tuple of the symbols for each of the 118 elements. The zeroth element is a placeholder."""


# The correct way to convert numpy arrays to bytes is different on Mac/"Darwin"
if platform == "darwin":
    # Mac
    def _array_to_bytes(array):
        r"""Convert a numpy.ndarray instance to bytes."""
        return array.tobytes()


else:
    # Linux and friends
    def _array_to_bytes(array):
        r"""Convert a numpy.ndarray instance to bytes."""
        return array.data if array.flags["C_CONTIGUOUS"] else array.tobytes()


@dataclass(eq=False, order=False)
class SpeciesData:
    r"""Properties of atomic and ionic species corresponding to fields in MessagePack files."""
    #
    # Species info
    #
    dataset: str = field()
    elem: str = field()
    natom: int = field()
    basis: str = field()
    nelec: int = field()
    nspin: int = field()
    nexc: int = field()
    #
    # Element properties
    #
    cov_radii: dict = field()
    vdw_radii: dict = field()
    mass: float = field()
    #
    # Electronic and molecular orbital energies
    #
    energy: float = field(default=None)
    mo_energies: ndarray = field(default=None)
    mo_occs: ndarray = field(default=None)
    #
    # Conceptual DFT related properties
    #
    ip: float = field(default=None)
    mu: float = field(default=None)
    eta: float = field(default=None)
    #
    # Radial grid
    #
    rs: ndarray = field(default=None)
    #
    # Density
    #
    dens_up: ndarray = field(default=None)
    dens_dn: ndarray = field(default=None)
    dens_tot: ndarray = field(default=None)
    dens_mag: ndarray = field(default=None)
    #
    # Derivative of density
    #
    d_dens_up: ndarray = field(default=None)
    d_dens_dn: ndarray = field(default=None)
    d_dens_tot: ndarray = field(default=None)
    d_dens_mag: ndarray = field(default=None)
    #
    # Laplacian
    #
    lapl_up: ndarray = field(default=None)
    lapl_dn: ndarray = field(default=None)
    lapl_tot: ndarray = field(default=None)
    lapl_mag: ndarray = field(default=None)
    #
    # Kinetic energy density
    #
    ked_up: ndarray = field(default=None)
    ked_dn: ndarray = field(default=None)
    ked_tot: ndarray = field(default=None)
    ked_mag: ndarray = field(default=None)


class Species(SpeciesData):
    r"""Properties of atomic and ionic species."""

    def __init__(self, *args, **kwargs):
        r"""Initialize a Species Instance."""
        # Initialize superclass
        SpeciesData.__init__(self, *args, **kwargs)
        #
        # Attributes declared here are not considered as part of the dataclasses interface,
        # and therefore are not included in the output of dataclasses.asdict(species_instance)
        #
        # Charge and multiplicity
        #
        self.charge = self.natom - self.nelec
        self.mult = self.nspin + 1

    #
    # Density splines
    #
    def dens_spline(self, points, spin='ab', index=None, log=False):
        """Compute electron density

        Parameters
        ----------
        points : ndarray, (N,)
            Radial grid points given as a 1D-array.
        spin : str, optional
            Type of occupied spin orbitals which can be either "a" (for alpha), "b" (for
            beta), and "ab" (for alpha + beta), by default 'ab'
        index : sequence of int, optional
            Sequence of integers representing the occupied spin orbitals which are indexed
            from 1 to the number basis functions. If ``None``, all orbitals of the given spin(s) are included, by default None
        log : bool, optional
            Whether the logarithm of the density is used for interpolation, by default False

        """
        spins = {'a': self.dens_up, 'b': self.dens_dn, 'ab': self.dens_tot, 'm': self.dens_mag}
        if index is None:
            if spins[spin] is not None:
                spline = cubic_interp(self.rs, spins[spin], log=log)
            else:
                raise ValueError(f'Density spline for occupied `{spin}` spin-orbitals unavailable')
        else:
            raise NotImplementedError('Desnity for a subset of orbitals is not supported yet.')
        return spline(points)

    def d_dens_spline(self, points, spin='ab', index=None, log=False):
        r"""Compute derivative of electron density.

        Parameters
        ----------
        points : ndarray, (N,)
            Radial grid points given as a 1D-array.
        spin : str, optional
            Type of occupied spin orbitals which can be either "a" (for alpha), "b" (for
            beta), and "ab" (for alpha + beta), by default 'ab'
        index : sequence of int, optional
            Sequence of integers representing the occupied spin orbitals which are indexed
            from 1 to the number basis functions. If ``None``, all orbitals of the given spin(s) are included, by default None
        log : bool, optional
            Whether the logarithm of the density is used for interpolation, by default False

        """
        spins = {'a': self.d_dens_up, 'b': self.d_dens_dn, 'ab': self.d_dens_tot, 'm': self.d_dens_mag}
        if index is None:
            if spins[spin] is not None:
                spline = cubic_interp(self.rs, spins[spin], log=log)
            else:
                raise ValueError(f'Density derivative spline for occupied `{spin}` spin-orbitals unavailable.')
        else:
            raise NotImplementedError('Desnity derivative for a subset of orbitals is not supported yet.')
        return spline(points)

    def ked_spline(self, points, spin='ab', index=None, log=True):
        r"""Compute positive definite kinetic energy density."""
        spins = {'a': self.ked_up, 'b': self.ked_dn, 'ab': self.ked_tot, 'm': self.ked_mag}
        if index is None:
            if spins[spin] is not None:
                spline = cubic_interp(self.rs, spins[spin], log=log)
            else:
                raise ValueError(f'Kinetic energy density for occupied `{spin}` spin-orbitals unavailable.')
        else:
            raise NotImplementedError('Kinetic energy density for a subset of orbitals is not supported yet.')
        return spline(points)

    def lapl_spline(self, points, spin='ab', index=None, log=False):
        r"""Compute Laplacian of electron density."""
        spins = {'a': self.lapl_up, 'b': self.lapl_dn, 'ab': self.lapl_tot, 'm': self.lapl_mag}
        if index is None:
            if spins[spin] is not None:
                spline = cubic_interp(self.rs, spins[spin], log=log)
            else:
                raise ValueError(f'Density laplacian for occupied `{spin}` spin-orbitals unavailable')
        else:
            raise NotImplementedError('Desnity laplacian for a subset of orbitals is not supported yet.')
        return spline(points)

    def to_dict(self):
        r"""Return the dictionary representation of the Species instance."""
        return asdict(self)

    def to_json(self):
        r"""Return the JSON string representation of the Species instance."""
        return dumps(asdict(self), cls=Species._JSONEncoder)

    class _JSONEncoder(JSONEncoder):
        r"""JSON encoder handling simple `numpy.ndarray` objects (for `Species.dump`)."""

        def default(self, obj):
            r"""Default encode function."""
            return obj.tolist() if isinstance(obj, ndarray) else JSONEncoder.default(self, obj)

    @staticmethod
    def _msgfile(elem, charge, mult, nexc, dataset, datapath):
        r"""Return the filename of a database entry MessagePack file."""
        return join(datapath, f"{dataset.lower()}/db/{elem}_{charge}_{mult}_{nexc}.msg")

    def _dump(self, datapath):
        r"""Dump the Species instance to a MessagePack file in the database."""
        # Get database entry filename
        fn = Species._msgfile(self.elem, self.charge, self.mult, self.nexc, self.dataset, datapath)
        # Convert numpy arrays to raw bytes for dumping as msgpack
        msg = {k: _array_to_bytes(v) if isinstance(v, ndarray) else v for k, v in asdict(self).items()}
        # Dump msgpack entry to database
        with open(fn, "wb") as f:
            f.write(pack_msg(msg))


def load(elem, charge, mult, nexc=0, dataset=DEFAULT_DATASET, datapath=DEFAULT_DATAPATH):
    r"""Load an atomic or ionic species from the AtomDB database."""
    # Load database msgpack entry
    with open(Species._msgfile(elem, charge, mult, nexc, dataset, datapath), "rb") as f:
        msg = unpack_msg(f)
    # Convert raw bytes back to numpy arrays, initialize the Species instance, return it
    return Species(**{k: frombuffer(v) if isinstance(v, bytes) else v for k, v in msg.items()})


def compile(elem, charge, mult, nexc=0, dataset=DEFAULT_DATASET, datapath=DEFAULT_DATAPATH):
    r"""Compile an atomic or ionic species into the AtomDB database."""
    # Ensure directories exist
    makedirs(join(datapath, f"{dataset}/db"), exist_ok=True)
    makedirs(join(datapath, f"{dataset}/raw"), exist_ok=True)
    # Import the compile script for the appropriate dataset
    submodule = import_module(f"atomdb.datasets.{dataset}")
    # Compile the Species instance and dump the database entry
    submodule.run(elem, charge, mult, nexc, dataset, datapath)._dump(datapath)


def datafile(suffix, elem, charge, mult, nexc=0, dataset=None, datapath=DEFAULT_DATAPATH):
    r"""Return the filename of a raw data file."""
    # Check that all non-optional arguments are specified
    if dataset is None:
        raise ValueError("Argument `dataset` cannot be unspecified")
    # Format the filename specified and return it
    suffix = f"{'' if suffix.startswith('.') else '_'}{suffix.lower()}"
    if dataset.split('_')[0] == 'hci':
        prefix = f"{str(element_number(elem)).zfill(3)}"
        tag = f"q{str(charge).zfill(3)}_m{mult:02d}_k{nexc:02}_sp_{dataset}"
    return join(datapath, f"{dataset.lower()}/raw/{prefix}_{tag}{suffix}")


def element_number(elem):
    r"""Return the element number from the given element symbol."""
    return ELEMENTS.index(elem) if isinstance(elem, str) else elem


def element_symbol(elem):
    r"""Return the element symbol from the given element number."""
    return elem if isinstance(elem, str) else ELEMENTS[elem]


def pack_msg(msg):
    r"""Pack an object to MessagePack binary format."""
    return Packer(use_bin_type=True).pack(msg)


def unpack_msg(msg):
    r"""Unpack an object from MessagePack binary format."""
    return Unpacker(msg, use_list=False, strict_map_key=True).unpack()


class interp1d_log(interp1d):
    r"""Interpolate over a 1-D grid."""

    def __init__(self, x, y, **kwargs):
        r"""Initialize the interp1d_log instance."""
        interp1d.__init__(self, x, log(y), **kwargs)

    def __call__(self, x):
        r"""Compute the interpolation at some x-values."""
        return exp(interp1d.__call__(self, x))


def cubic_interp(x, y, log=False):
    r"""Create an interpolated cubic spline for the given data."""
    cls = interp1d_log if log else interp1d
    return cls(x, y, kind="cubic", copy=False, fill_value="extrapolate", assume_sorted=True)


def get_element_data(elem):
    r"""Get element properties from elements.csv.

    The following attributes are present for some elements. When a parameter
    is not known for a given element, the attribute is set to `None`.
    mass
        The IUPAC atomic masses (wieghts) of 2013.
        T.B. Coplen, W.A. Brand, J. Meija, M. Gröning, N.E. Holden, M.
        Berglund, P. De Bièvre, R.D. Loss, T. Prohaska, and T. Walczyk.
        http://ciaaw.org, http://www.ciaaw.org/pubs/TSAW2013_xls.xls,
        When ranges are provided, the middle of the range is used.
    cov_radius_cordero
        Covalent radius. B. Cordero, V. Gomez, A. E. Platero-Prats, M.
        Reves, J. Echeverria, E. Cremades, F. Barragan, and S. Alvarez,
        Dalton Trans. pp. 2832--2838 (2008), URL
        http://dx.doi.org/10.1039/b801115j
    cov_radius_bragg
        Covalent radius. W. L. Bragg, Phil. Mag. 40, 169 (1920), URL
        http://dx.doi.org/10.1080/14786440808636111
    cov_radius_slater
        Covalent radius. J. C. Slater, J. Chem. Phys. 41, 3199 (1964), URL
        http://dx.doi.org/10.1063/1.1725697
    vdw_radius_bondi
        van der Waals radius. A. Bondi, J. Phys. Chem. 68, 441 (1964), URL
        http://dx.doi.org/10.1021/j100785a001
    vdw_radius_truhlar
        van der Waals radius. M. Mantina A. C. Chamberlin R. Valero C. J.
        Cramer D. G. Truhlar J. Phys. Chem. A 113 5806 (2009), URL
        http://dx.doi.org/10.1021/jp8111556
    vdw_radius_rt
        van der Waals radius. R. S. Rowland and R. Taylor, J. Phys. Chem.
        100, 7384 (1996), URL http://dx.doi.org/10.1021/jp953141+
    vdw_radius_batsanov
        van der Waals radius. S. S. Batsanov Inorganic Materials 37 871
        (2001), URL http://dx.doi.org/10.1023/a%3a1011625728803
    vdw_radius_dreiding
        van der Waals radius. Stephen L. Mayo, Barry D. Olafson, and William
        A. Goddard III J. Phys. Chem. 94 8897 (1990), URL
        http://dx.doi.org/10.1021/j100389a010
    vdw_radius_uff
        van der Waals radius. A. K. Rappi, C. J. Casewit, K. S. Colwell, W.
        A. Goddard III, and W. M. Skid J. Am. Chem. Soc. 114 10024 (1992),
        URL http://dx.doi.org/10.1021/ja00051a040
    vdw_radius_mm3
        van der Waals radius. N. L. Allinger, X. Zhou, and J. Bergsma,
        Journal of Molecular Structure: THEOCHEM 312, 69 (1994),
        http://dx.doi.org/10.1016/s0166-1280(09)80008-0
    """

    z = element_number(elem)
    convertor_types = {
        'int': (lambda s: int(s)),
        'float': (lambda s : float(s)),
        'au': (lambda s : float(s)),    # just for clarity, atomic units
        'str': (lambda s: s.strip()),
        "angstrom": (lambda s: float(s) * angstrom),
        "2angstrom": (lambda s: float(s) * angstrom / 2),
        "angstrom**3": (lambda s: float(s) * angstrom ** 3),
        "amu": (lambda s: float(s) * amu),
    }

    with open(join(dirname(__file__), "data/elements.csv"), "r") as f:
        rows = reader(f)
        # Skip information about data provenance
        for row in rows:
            if len(row[1]) > 0:
                break
        # parse the first two header rows
        names = row
        convertors = [convertor_types[unit] for unit in next(rows)]
        data = list(rows)

        cov_radii = {}
        vdw_radii = {}
        for idx, (name, val) in enumerate(zip(names, data[z])):
            if 'cov_radius' in name:
                kval = name.split("_")[-1]
                cov_radii[kval] = convertors[idx](val) if val is not "" else None
            elif 'vdw_radius' in name:
                kval = name.split("_")[-1]
                vdw_radii[kval] = convertors[idx](val) if val is not "" else None
            elif name == 'mass':
                mass = convertors[idx](val)
    return cov_radii, vdw_radii, mass
