# Licensed under a 3-clause BSD style license - see LICENSE.rst

"""
This module contains the base classes and frameworks for coordinate objects.
"""
from abc import ABCMeta, abstractproperty, abstractmethod

from .. import units as u
from .angles import RA, Dec, Angle, AngularSeparation
from .distances import *

__all__ = ['SphericalCoordinatesBase']


class SphericalCoordinatesBase(object):
    """
    Abstract superclass for all coordinate classes representing points
    in three dimensions.

    Notes
    -----
    Subclasses must implement `__init__`, and define the `latangle` and
    `lonangle` properties.  They may also override the `equinox`
    property, or leave it unaltered to indicate the coordinates are
    equinoxless.

    `_initialize_latlon` is provided to implement typical
    initialization features, and should be called from a subclass'
    `__init__`.  See the classes in
    `astropy.coordinates.builtin_systems` for examples of this.
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def __init__(self, *args, **kwargs):
        """
        Subclasses must override this, but they should also call this to set up
        internal state.
        """
        self._distance = None
        self._cartpoint = None

    def __eq__(self, other):
        try:
            return (self.latangle == other.latangle and
                    self.lonangle == other.lonangle and
                    self.distance == other.distance and
                    self.equinox == other.equinox)
        except AttributeError:
            return False

    _init_docstring_param_templ = """coordstr : str
        A single string with the coordinates.  Cannot be used with
        `{latnm}` and `{lonnm}` nor `x`/`y`/`z`.
    {lonnm} : `~astropy.coordinates.angle.Angle`, float, int, str
        This must be given with `{latnm}`.
    {latnm} : `~astropy.coordinates.angle.Angle`, float, int, str
        This must be given with `{lonnm}`.
    distance : `~astropy.coordinates.coordsystems.Distance`, optional
        This may be given with `{latnm}` and `{lonnm}` or `coordstr`
        and not `x`, `y`, or `z`.  If not given, `None` (unit sphere)
        will be assumed.
    x : number
        The first cartesian coordinate. Must be given with `y` and `z`
        and not with `{lonnm}` or `{latnm}` nor `coordstr`.
    y : number
        The second cartesian coordinate. Must be given with `x` and `z`
        and not with `{lonnm}` or `{latnm}` nor `coordstr`.
    z : number
        The third cartesian coordinate. Must be given with `x` and `y`
        and not with `{lonnm}` or `{latnm}` nor `coordstr`.
    cartpoint : `~astropy.coordinates.distance.CartesianPoints`
        A cartesian point with the coordinates.  Cannot be used with
        any other arguments.
    unit : `~astropy.units.UnitBase` or tuple

        * If `{lonnm}` and `{latnm}` or `coordstr` are given:
            If the units cannot be determined from the angle values
            provided, they must be specified as a tuple. The first value
            in the tuple is paired with `{lonnm}`, and the second with
            `{latnm}`. If `coordstr` is applied or `{latnm}` is a string
            and a single unit is  given, it is assumed to apply to
            `{lonnm}`. Otherwise, a single unit is applied to both.

        * If `x`, `y`, and `z` are given:
            `unit` must be present have dimensions of length"""

    def _initialize_latlon(self, lonname, latname, useradec, initargs, initkwargs):
        """
        Subclasses should use this to initialize standard lat/lon-style
        coordinates.

        This recognizes both the lat/lon style and the cartesian form.

        Parameters
        ----------
        lonname : str
            The name of the longitude-like coordinate attribute
        latname : str
            The name of the latitude-like coordinate attribute
        useradec : bool
            If True, the `RA` and `Dec` classes will be used for the
            angles.  Otherwise, a basic `Angle` will be used.
        initargs : list
            The ``*args`` from the initializer
        initkwargs : dict
            The ``**kwargs`` from the initializer
        """
        initkwargs = dict(initkwargs)  # copy
        nargs = len(initargs)
        sclsnm = self.__class__.__name__

        if nargs == 1:
            if isinstance(initargs[0], CartesianPoints):
                initkwargs['cartpoint'] = initargs[0]
            else:
                initkwargs['coordstr'] = initargs[0]
        if nargs > 1:
            if lonname in initkwargs:
                raise TypeError("{0} got multiple values for keyword argument "
                                "'{1}'".format(sclsnm, lonname))
            initkwargs[lonname] = initargs[0]
        if nargs >= 2:
            if latname in initkwargs:
                raise TypeError("{0} got multiple values for keyword argument "
                                "'{1}'".format(sclsnm, latname))
            initkwargs[latname] = initargs[1]
        if nargs > 2:
            raise TypeError('{0} takes up to 2 positional arguments '
                            '({1} given)'.format(sclsnm, len(initargs)))

        unit = initkwargs.pop('unit', None)
        coordstr = initkwargs.pop('coordstr', None)
        lonval = initkwargs.pop(lonname, None)
        latval = initkwargs.pop(latname, None)
        distval = initkwargs.pop('distance', None)
        cartpoint = initkwargs.pop('cartpoint', None)
        x = initkwargs.pop('x', None)
        y = initkwargs.pop('y', None)
        z = initkwargs.pop('z', None)

        if len(initkwargs) > 0:
            raise TypeError('{0} got unexpected keyword argument'
                            ' {1}'.format(sclsnm, initkwargs.keys()))

        ll = lonval is not None and latval is not None
        xyz = x is not None or y is not None or z is not None

        if (ll or coordstr is not None) and not xyz and cartpoint is None:
            # lat/lon-style initialization

            units = [] if unit is None else unit

            if isinstance(units, tuple) or isinstance(units, list):
                if len(units) > 2:
                    raise ValueError('Cannot give more than 2 units while '
                                     'initializing a coordinate')
            elif isinstance(units, u.UnitBase) or isinstance(units, basestring):
                # Only a single unit given, which is fine.  If the arguments are
                # strings, assign it to just the lon, otherwise both
                if coordstr is not None or isinstance(latval, basestring):
                    units = (units, )
                else:
                    units = (units, units)
            else:
                raise ValueError("The value for units must be given as a tuple, e.g. "
                                 "unit=(u.hour, u.degree). An object of type '{0}' "
                                 "was given.".format(type(units).__name__))

            if coordstr is not None:
                # need to try to parse the coordinate from a single argument
                # populates latval and lonval variables, which then get made
                # into coordinates below
                x = coordstr
                if isinstance(coordstr, basestring):
                    parsed = False
                    if "," in x:
                        lonval, latval = x.split(",")
                        parsed = True
                    elif "\t" in x:
                        lonval, latval = x.split("\t")
                        parsed = True
                    elif len(x.split()) == 6:
                        lonval = " ".join(x.split()[0:3])
                        latval = " ".join(x.split()[3:])
                        parsed = True
                    elif len(x.split()) == 2:
                        lonval, latval = x.split()
                        parsed = True

                    if not parsed:
                        values = x.split()
                        i = 1
                        while i < len(values) and not parsed:
                            try:
                                lonval = " ".join(values[0:i])
                                parsed = True
                            except:
                                i += 1

                        if parsed == True:
                            latval = " ".join(values[i:])

                    if not parsed:
                        msg = ("Could not parse {lonname}/{latname} values "
                               "from the string provided: '{coordstr}'.")
                        raise ValueError(msg.format(lonname=lonname,
                                                    latname=latname,
                                                    coordstr=coordstr))
                else:
                    raise ValueError("A {0} cannot be created with a value of type "
                                     "'{1}'.".format(sclsnm, type(coordstr).__name__))
            if useradec:
                lonang = RA(lonval, unit=units[0]) if len(units) > 0 else RA(lonval)
                latang = Dec(latval, unit=units[1]) if len(units) > 1 else Dec(latval)
            else:
                if isinstance(lonval, RA):
                    raise TypeError('Cannot provide an RA object to non-RA/Dec system {0}'.format(sclsnm))
                if isinstance(latval, Dec):
                    raise TypeError('Cannot provide a Dec object to non-RA/Dec system {0}'.format(sclsnm))
                lonang = Angle(lonval, unit=units[0]) if len(units) > 0 else Angle(lonval)
                latang = Angle(latval, unit=units[1]) if len(units) > 1 else Angle(latval)
            dist = None if distval is None else Distance(distval)  # copy

        elif (xyz or cartpoint is not None) and not ll and distval is None and coordstr is None:
            #cartesian-style initialization
            if cartpoint is not None:
                if xyz or unit is not None:
                    raise ValueError('Cannot give both a CartesianPoints and x/y/z/units')
                x = cartpoint.x
                y = cartpoint.y
                z = cartpoint.z
                unit = cartpoint.unit
            r, latval, lonval = cartesian_to_spherical(x, y, z)

            if useradec:
                lonang = RA(lonval, unit=u.radian)
                latang = Dec(latval, unit=u.radian)
            else:
                lonang = Angle(lonval, unit=u.radian)
                latang = Angle(latval, unit=u.radian)

            dist = None if unit is None else Distance(r, unit)

        else:
            raise TypeError('Must initialize {coordnm} with '
                            '{latname}/{lonname}/(distance) or x/y/z '
                            ''.format(coordnm=sclsnm, latname=latname,
                                      lonname=lonname))
        setattr(self, lonname, lonang)
        setattr(self, latname, latang)
        self._distance = dist


    @abstractproperty
    def latangle(self):
        """
        The latitudinal/elevation angle for these coordinates as an
        `~astropy.coorinates.angles.Angle` object.

        .. note ::
            This should be overridden in subclasses as a read-only property that
            just returns an attribute a way to abstract the exact choice of
            names for the coordiantes. E.g., `ICRSCoordinates` implements this
            by doing ``return self.ra``.
        """

    @abstractproperty
    def lonangle(self):
        """
        The longitudinal/azimuthal angle for these coordinates as an
        `~astropy.coorinates.angles.Angle` object.

        .. note ::
            This should be overridden in subclasses as a read-only property that
            just returns an attribute a way to abstract the exact choice of
            names for the coordinates. E.g., `ICRSCoordinates` implements this
            by doing ``return self.dec``.
        """

    @property
    def equinox(self):
        """
        The equinox of this system, or None to indicate no equinox specified.
        """
        return None

    @property
    def distance(self):
        """
        The radial distance for this coordinate object as an
        `~astropy.coordinates.coordsystems.Distance` object.

        If set as a tuple, the tuple will be passed into the
        `~astropy.coordinates.coordsystems.Distance` constructor.

        Alternatively, this may be `None`, indicating an unknown/not given
        distance. Where necessary, this object will be interpreted as angles on
        the unit sphere.
        """
        return self._distance

    @distance.setter
    def distance(self, val):
        if val is None:
            self._distance = None
        elif isinstance(val, tuple):
            self._distance = Distance(*val)
        elif isinstance(val, Distance):
            self._distance = val
        else:
            raise TypeError('Spherical coordinate distance must be a ')

    @property
    def x(self):
        self._make_cart()
        return self._cartpoint.x

    @property
    def y(self):
        self._make_cart()
        return self._cartpoint.y

    @property
    def z(self):
        self._make_cart()
        return self._cartpoint.z

    @property
    def cartesian(self):
        self._make_cart()
        return self._cartpoint

    def _make_cart(self, override=False):
        if override or self._cartpoint is None:
            if self._distance is None:
                r = 1
                runit = None
            else:
                r = self._distance._value
                runit = self._distance._unit
            x, y, z = spherical_to_cartesian(r, self.latangle.radians,
                                                self.lonangle.radians)
            self._cartpoint = CartesianPoints(x, y, z, runit)

    def separation(self, other):
        """
        Computes on-sky separation between this coordinate and another.

        Parameters
        ----------
        other : `~astropy.coordinates.coordsystems.SphericalCoordinatesBase`
            The coordinate system to get the separation to.

        Returns
        -------
        sep : `~astropy.coordinates.angles.AngularSeparation`
            The on-sky separation between this and the `other` coordinate.
        """
        other_in_self_system = other.transform_to(self.__class__)

        lat1 = self.latangle.radians
        lat2 = other_in_self_system.latangle.radians
        lon1 = self.lonangle.radians
        lon2 = other_in_self_system.lonangle.radians
        return AngularSeparation(lat1, lon1, lat2, lon2, u.radian)

    def separation3d(self, other):
        """
        Computes three dimensional separation between this coordinate
        and another.

        Parameters
        ----------
        other : `~astropy.coordinates.coordsystems.SphericalCoordinatesBase`
            The coordinate system to get the distance to.

        Returns
        -------
        sep : `~astropy.coordinates.coordsystems.Distance`
            The real-space distance between these two coordinates.

        Raises
        ------
        ValueError
            If this or the other coordinate do not have distances.
        """
        if self._distance is None:
            raise ValueError('This object does not have a distance; cannot '
                             'compute 3d separation.')

        # do this first just in case the conversion somehow creates a distance
        other_in_self_system = other.transform_to(self.__class__)

        if other_in_self_system._distance is None:
            raise ValueError('The other object does not have a distance; '
                             'cannot compute 3d separation.')

        dscale = other_in_self_system._distance._unit.to(self._distance._unit, 1)

        dx = self.x - other_in_self_system.x * dscale
        dy = self.y - other_in_self_system.y * dscale
        dz = self.z - other_in_self_system.z * dscale

        distval = (dx ** 2 + dy ** 2 + dz ** 2) ** 0.5
        return Distance(distval, self._distance._unit)

    #<------------transformation-related stuff here-------------------->
    def transform_to(self, tosys):
        """
        Transform this coordinate to a new system.

        Parameters
        ----------
        tosys : class
            The system to transform this coordinate into.

        Returns
        -------
        transcoord
            A new object with this coordinate represented in the `tosys` system.

        Raises
        ------
        ValueError
            If there is no possible transformation route.
        """
        from copy import deepcopy
        from .transformations import master_transform_graph
        from .errors import ConvertError

        if tosys is self.__class__:
            return deepcopy(self)

        trans = master_transform_graph.get_transform(self.__class__, tosys)
        if trans is None:
            raise ConvertError('Cannot transform from {0} to '
                               '{1}'.format(self.__class__, tosys))
        return trans(self)

    def is_transformable_to(self, tosys):
        """
        Determines if this coordinate can be transformed to a particular system.

        Parameters
        ----------
        tosys : class
            The system to transform this coordinate into.

        Returns
        -------
        transformable : bool or str
            True if this can be trasnformed to `tosys`, False if not. The
            string 'same' if `tosys` is the same system as this object
            (i.e. no transformation is needed).
        """
        from .transformations import master_transform_graph

        if self.__class__ is tosys:
            return 'same'
        else:
            trans = master_transform_graph.get_transform(self.__class__, tosys)
            return trans is not None

    def __getattr__(self, name):
        """
        Overrides getattr to return coordinates that this can be transformed
        to, based on the alias name in the master transform graph.
        """
        from .transformations import master_transform_graph

        nmsys = master_transform_graph.lookup_name(name)
        if self.__class__ is nmsys:
            return self
        if nmsys is not None and self.is_transformable_to(nmsys):
            return self.transform_to(nmsys)
        else:
            msg = "'{0}' object has no attribute '{1}', nor a transform."
            raise AttributeError(msg.format(self.__class__.__name__, name))

    def __dir__(self):
        """
        Overriding the builtin `dir` behavior allows us to add the
        transforms available by aliases.  This also allows ipython
        tab-completion to know about the transforms.
        """
        from .transformations import master_transform_graph

        # the stuff `dir` normally gives
        dir_items = dir(type(self)) + self.__dict__.keys()

        # determine the aliases that this can be transformed to.
        for alias in master_transform_graph.get_aliases():
            tosys = master_transform_graph.lookup_name(alias)
            if self.is_transformable_to(tosys):
                dir_items.append(alias)

        return sorted(set(dir_items))
