# -*- coding: utf-8 -*-
# Licensed under a 3-clause BSD style license - see LICENSE.rst

"""
Defines physical unit names.

This module is not intended for use by user code directly.  Instead,
the physical unit name of a `Unit` can be obtained using its `ptype`
property.
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

from . import core
from . import si
from . import astrophys


__all__ = ['def_physical_type', 'get_physical_type']


_physical_unit_mapping = {}


def _tuple_repr(unit):
    """
    Creates a canonical representation of a (possibly compound)
    unit that can be used as a dictionary key.  This makes looking
    up other units with the same signature easy.

    Parameters
    ----------
    unit : `~astropy.units.UnitBase` instance
        The unit to create a tuple for.

    Returns
    -------
    canonical : tuple
        A canonical, hashable representation of the unit.
    """
    unit = unit.decompose()
    r = zip([unicode(x) for x in unit.bases], unit.powers)
    r.sort()
    r = tuple(r)
    return r


def def_physical_type(unit, name):
    """
    Adds a new physical unit mapping.

    Parameters
    ----------
    unit : `~astropy.units.UnitBase` instance
        The unit to map from.

    name : str
        The physical name of the unit.
    """
    r = _tuple_repr(unit)
    if r in _physical_unit_mapping:
        raise ValueError(
            "{0!r} ({1!r}) already defined as {2!r}".format(
                r, name, _physical_unit_mapping[r]))
    _physical_unit_mapping[r] = name


def get_physical_type(unit):
    """
    Given a unit, returns the name of the physical quantity it
    represents.  If it represents an unknown physical quantity,
    ``"unknown"`` is returned.

    Parameters
    ----------
    unit : `~astropy.units.UnitBase` instance
        The unit to lookup

    Returns
    -------
    physical : str
        The name of the physical quantity, or unknown if not
        known.
    """
    r = _tuple_repr(unit)
    return _physical_unit_mapping.get(r, 'unknown')


for unit, name in [
    (core.Unit(1), 'dimensionless'),
    (si.m, 'length'),
    (si.m ** 2, 'area'),
    (si.m ** 3, 'volume'),
    (si.s, 'time'),
    (si.rad, 'angle'),
    (si.sr, 'solid angle'),
    (si.m / si.s, 'speed'),
    (si.m / si.s ** 2, 'acceleration'),
    (si.Hz, 'frequency'),
    (si.g, 'mass'),
    (si.mol, 'amount of substance'),
    (si.K, 'temperature'),
    (si.N, 'force'),
    (si.J, 'energy'),
    (si.Pa, 'pressure'),
    (si.W, 'power'),
    (si.kg / si.m ** 3, 'mass density'),
    (si.m ** 3 / si.kg, 'specific volume'),
    (si.mol / si.m ** 3, 'molar volume'),
    (si.kg * si.m / si.s, 'momentum/impulse'),
    (si.kg * si.m ** 2 / si.s, 'angular momentum'),
    (si.rad / si.s, 'angular speed'),
    (si.rad / si.s ** 2, 'angular acceleration'),
    (si.g / (si.m * si.s), 'dynamic viscosity'),
    (si.m ** 2 / si.s, 'kinematic viscosity'),
    (si.m ** -1, 'wavenumber'),
    (si.A, 'electrical current'),
    (si.C, 'electrical charge'),
    (si.V, 'electrical potential'),
    (si.Ohm, 'electrical resistance'),
    (si.S, 'electrical conductance'),
    (si.F, 'electrical capacitance'),
    (si.C * si.m, 'electrical dipole moment'),
    (si.A / si.m ** 2, 'electrical current density'),
    (si.V / si.m, 'electrical field strength'),
    (si.C / si.m ** 2, 'electrical flux density'),
    (si.C / si.m ** 3, 'electrical charge density'),
    (si.F / si.m, 'permittivity'),
    (si.Wb, 'magnetic flux'),
    (si.T, 'magnetic flux density'),
    (si.A / si.m, 'magnetic field strength'),
    (si.H / si.m, 'electromagnetic field strength'),
    (si.H, 'inductance'),
    (si.cd, 'luminous intensity'),
    (si.lm, 'luminous flux'),
    (si.lx, 'luminous emittence/illuminance'),
    (si.W / si.sr, 'radiant intensity'),
    (si.cd / si.m ** 2, 'luminance'),
    (astrophys.Jy, 'spectral flux density'),
    (astrophys.R, 'photon flux'),
    (astrophys.bit, 'data quantity'),
    (astrophys.bit / si.s, 'bandwidth')
]:
    def_physical_type(unit, name)
