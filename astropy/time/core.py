"""
The astropy.time package provides functionality for manipulating times and
dates. Specific emphasis is placed on supporting time scales (e.g. UTC, TAI,
UT1) and time representations (e.g. JD, MJD, ISO 8601) that are used in
astronomy.
"""
import sys
import time
import itertools
import numpy as np

try:
    from . import sofa_time
except ImportError:
    pass

MJD_ZERO = 2400000.5
SECS_PER_DAY = 86400

# These both get filled in at end after TimeFormat subclasses defined
TIME_FORMATS = {}
TIME_DELTA_FORMATS = {}

TIME_SCALES = ('tai', 'tcb', 'tcg', 'tdb', 'tt', 'ut1', 'utc')
TIME_DELTA_SCALES = ('tai',)

MULTI_HOPS = {('tai', 'tcb'): ('tt', 'tdb'),
              ('tai', 'tcg'): ('tt',),
              ('tai', 'ut1'): ('utc',),
              ('tai', 'tdb'): ('tt',),
              ('tcb', 'tcg'): ('tdb', 'tt'),
              ('tcb', 'tt'): ('tdb',),
              ('tcb', 'ut1'): ('tdb', 'tt', 'tai', 'utc'),
              ('tcb', 'utc'): ('tdb', 'tt', 'tai'),
              ('tcg', 'tdb'): ('tt', 'tdb'),
              ('tcg', 'ut1'): ('tt', 'tai', 'utc'),
              ('tcg', 'utc'): ('tt', 'tai'),
              ('tdb', 'ut1'): ('tt', 'tai', 'utc'),
              ('tdb', 'utc'): ('tt', 'tai'),
              ('tt', 'ut1'): ('tai', 'utc'),
              ('tt', 'utc'): ('tai',),
              }


class Time(object):
    """Represent and manipulate times and dates for astronomy.

    A Time object is initialized with one or more times in the ``val``
    argument.  The input times in ``val`` must conform to the specified
    ``format`` and must correspond to the specified time ``scale``.  The
    optional ``val2`` time input should be supplied only for numeric input
    formats (e.g. JD) where very high precision (better than 64-bit precision)
    is required.

    Parameters
    ----------
    val : numpy ndarray, list, str, or number
        Data to initialize table.
    val2 : numpy ndarray, list, str, or number; optional
        Data to initialize table.
    format : str, optional
        Format of input value(s)
    scale : str, optional
        Time scale of input value(s)
    opt : dict, optional
        options
    lat : float, optional
        Earth latitude of observer
    lon : float, optional
        Earth longitude of observer
    """

    _precision = 3  # Precision when for seconds as floating point
    _in_subfmt = '*'  # Select subformat for inputting string times
    _out_subfmt = '*'  # Select subformat for outputting string times

    def __init__(self, val, val2=None, format=None, scale=None,
                 precision=None, in_subfmt=None, out_subfmt=None,
                 lat=0.0, lon=0.0):
        self.SCALES = TIME_SCALES
        self.FORMATS = TIME_FORMATS
        self.lat = lat
        self.lon = lon
        if precision is not None:
            self.precision = precision
        if in_subfmt is not None:
            self.in_subfmt = in_subfmt
        if out_subfmt is not None:
            self.out_subfmt = out_subfmt
        self._init_from_vals(val, val2, format, scale)

    def _init_from_vals(self, val, val2, format, scale):
        if 'astropy.time.sofa_time' not in sys.modules:
            raise ImportError('Failed to import astropy.time.sofa_time '
                              'extension module (check installation)')

        # Coerce val into a 1-d array
        val, val_ndim = _make_1d_array(val)

        # If val2 is None then replace with zeros of the same length
        if val2 is None:
            val2 = np.zeros(len(val), dtype=np.double)
            val2_ndim = val_ndim
        else:
            val2, val2_ndim = _make_1d_array(val2)

        # Consistency checks
        if len(val) != len(val2):
            raise ValueError('Input val and val2 must match in length')

        self.is_scalar = (val_ndim == 0)
        if val_ndim != val2_ndim:
            raise ValueError('Input val and val2 must have same dimensions')

        if scale is not None and scale not in self.SCALES:
            raise ValueError('Scale {0} is not in the allowed scales {1}'
                             .format(scale, sorted(self.SCALES)))

        # Parse / convert input values into internal jd1, jd2 based on format
        self._format, self._time = self._get_time_fmt(val, val2, format, scale)
        self._scale = scale

    def _get_time_fmt(self, val, val2, format, scale):
        """Given the supplied val, val2, format and scale try to instantiate
        the corresponding TimeFormat class to convert the input values into
        the internal jd1 and jd2.

        If format is None and the input is a string-type array then guess
        available string formats and stop when one matches.
        """
        if format is None and val.dtype.kind == 'S':
            formats = [(name, cls) for name, cls in self.FORMATS.items()
                       if issubclass(cls, TimeString)]
            err_msg = 'any of format classes {0}'.format(
                [name for name, cls in formats])
        elif format not in self.FORMATS:
            raise ValueError('Must supply valid format in {0}'
                             .format(sorted(self.FORMATS)))
        else:
            formats = [(format, self.FORMATS[format])]
            err_msg = 'format class {0}'.format(format)

        for format, FormatClass in formats:
            try:
                return format, FormatClass(val, val2, scale, self.precision,
                                           self.in_subfmt, self.out_subfmt)
            except (ValueError, TypeError):
                pass
        else:
            raise ValueError('Input values did not match {0}'.format(err_msg))

    @property
    def format(self):
        """Time format
        """
        return self._format

    def __repr__(self):
        return ("<%s object: scale='%s' format='%s' vals=%s>" % (
                self.__class__.__name__,
                self.scale, self.format, getattr(self, self.format)))

    def __str__(self):
        return str(getattr(self, self.format))

    @property
    def scale(self):
        """Time scale
        """
        return self._scale

    def _set_scale(self, scale):
        if scale == self._scale:
            return
        if scale not in self.SCALES:
            raise ValueError('Scale {0} is not in the allowed scales {1}'
                             .format(scale, sorted(self.SCALES)))

        # Determine the chain of scale transformations to get from the current
        # scale to the new scale.  MULTI_HOPS contains a dict of all
        # transformations (xforms) that require intermediate xforms.
        # The MULTI_HOPS dict is keyed by (sys1, sys2) in alphabetical order.
        xform = (self._scale, scale)
        xform_sort = tuple(sorted(xform))
        multi = MULTI_HOPS.get(xform_sort, ())
        xforms = xform_sort[:1] + multi + xform_sort[-1:]
        # If we made the reverse xform then reverse it now.
        if xform_sort != xform:
            xforms = tuple(reversed(xforms))

        # Transform the jd1,2 pairs through the chain of scale xforms.
        jd1, jd2 = self._time.jd1, self._time.jd2
        for sys1, sys2 in itertools.izip(xforms[:-1], xforms[1:]):
            # Some xforms require an additional delta_ argument that is
            # provided through Time methods.  These values may be supplied by
            # the user or computed based on available approximations.  The
            # get_delta_ methods are available for only one combination of
            # sys1, sys2 though the property applies for both xform directions.
            args = [jd1, jd2]
            for sys12 in ((sys1, sys2), (sys2, sys1)):
                dt_method = 'get_delta_{0}_{1}'.format(*sys12)
                try:
                    get_dt = getattr(self, dt_method)
                except AttributeError:
                    pass
                else:
                    args.append(get_dt(jd1, jd2))
                    break

            conv_func = getattr(sofa_time, sys1 + '_' + sys2)
            jd1, jd2 = conv_func(*args)
        self._time = self.FORMATS[self.format](jd1, jd2, scale, self.precision,
                                               self.in_subfmt, self.out_subfmt,
                                               from_jd=True)
        self._scale = scale

    # Precision
    def _get_precision(self):
        return self._precision

    def _set_precision(self, val):
        if not isinstance(val, int) or val < 0 or val > 9:
            raise ValueError('precision attribute must be an int between '
                             '0 and 9')
        self._precision = val

    precision = property(_get_precision, _set_precision)
    """Decimal precision when outputting seconds as floating point (int value
    between 0 and 9 inclusive)."""

    # In_subfmt
    def _get_in_subfmt(self):
        return self._in_subfmt

    def _set_in_subfmt(self, val):
        if not isinstance(val, basestring):
            raise ValueError('in_subfmt attribute must be a string')
        self._in_subfmt = val

    in_subfmt = property(_get_in_subfmt, _set_in_subfmt)
    """Unix glob to select subformats for parsing string input times"""

    # Out_subfmt
    def _get_out_subfmt(self):
        return self._out_subfmt

    def _set_out_subfmt(self, val):
        if not isinstance(val, basestring):
            raise ValueError('out_subfmt attribute must be a string')
        self._out_subfmt = val

    out_subfmt = property(_get_out_subfmt, _set_out_subfmt)
    """Unix glob to select subformats for outputting times"""

    @property
    def jd1(self):
        """First of the two doubles that internally store time value(s) in JD
        """
        vals = self._time.jd1
        return (vals[0].tolist() if self.is_scalar else vals)

    @property
    def jd2(self):
        """Second of the two doubles that internally store time value(s) in JD
        """
        vals = self._time.jd2
        return (vals[0].tolist() if self.is_scalar else vals)

    @property
    def vals(self):
        """Time values expressed the current format
        """
        return self._time.vals

    def _get_time_object(self, format):
        """Turn this into copy??"""
        tm = self.__class__(self._time.jd1, self._time.jd2,
                            format='jd', scale=self.scale)
        attrs = ('is_scalar', '_precision', '_in_subfmt', '_out_subfmt',
                 '_delta_ut1_utc', '_delta_tdb_tt',
                 'lat', 'lon')
        for attr in attrs:
            try:
                setattr(tm, attr, getattr(self, attr))
            except AttributeError:
                pass

        # Now create the _time object for the given new format

        NewFormat = tm.FORMATS[format]
        # If the new format class has a "scale" class attr then that scale is
        # required and the input jd1,2 has to be converted first.
        if hasattr(NewFormat, 'scale'):
            scale = getattr(NewFormat, 'scale')
            new = getattr(tm, scale)  # self JDs converted to scale
            tm._time = NewFormat(new._time.jd1, new._time.jd2, scale,
                                   tm.precision,
                                   tm.in_subfmt, tm.out_subfmt,
                                   from_jd=True)
        else:
            tm._time = NewFormat(tm._time.jd1, tm._time.jd2,
                                   tm.scale, tm.precision,
                                   tm.in_subfmt, tm.out_subfmt,
                                   from_jd=True)
        tm._format = format

        return tm

    def __getattr__(self, attr):
        if attr in self.SCALES:
            tm = self._get_time_object(format=self.format)
            tm._set_scale(attr)
            return tm

        elif attr in self.FORMATS:
            tm = self._get_time_object(format=attr)
            return (tm.vals[0].tolist() if self.is_scalar else tm.vals)

        else:
            # Should raise AttributeError
            return self.__getattribute__(attr)

    def _match_len(self, val):
        """Ensure that `val` is matched to length of self.
        If val has length 1 then broadcast, otherwise cast to double
        and make sure length matches.
        """
        val, ndim = _make_1d_array(val)
        if len(val) == 1:
            oval = val
            val = np.empty(len(self), dtype=np.double)
            val[:] = oval
        elif len(val) != len(self):
            raise ValueError('Attribute length must match Time object length')
        return val

    # SOFA DUT arg = UT1 - UTC
    def get_delta_ut1_utc(self, jd1, jd2):
        """Sec. 4.3.1: the arg DUT is the quantity delta_UT1 = UT1 - UTC in
        seconds. It can be obtained from tables published by the IERS.
        XXX - get that table when needed and interpolate or whatever.
        """
        if not hasattr(self, '_delta_ut1_utc'):
            self._delta_ut1_utc = np.zeros(len(self), dtype=np.double)

        return self._delta_ut1_utc

    def set_delta_ut1_utc(self, val):
        self._delta_ut1_utc = self._match_len(val)

    # SOFA DTR arg = TDB - TT
    def get_delta_tdb_tt(self, jd1, jd2):
        if not hasattr(self, '_delta_tdb_tt'):
            # First go from the current input time (which is either
            # TDB or TT) to an approximate UTC.  Since TT and TDB are
            # pretty close (few msec?), assume TT.
            njd1, njd2 = sofa_time.tt_tai(jd1, jd2)
            njd1, njd2 = sofa_time.tai_utc(njd1, njd2)
            # XXX actually need to go to UT1 which needs DUT.
            ut = njd1 + njd2

            # Compute geodetic params needed for d_tdb_tt()
            phi = np.radians(self.lat)
            elon = np.radians(self.lon)
            xyz = sofa_time.iau_gd2gc(1, elon, phi, 0.0)
            u = np.sqrt(xyz[0] ** 2 + xyz[1] ** 2)
            v = xyz[2]

            self._delta_tdb_tt = sofa_time.d_tdb_tt(jd1, jd2, ut, elon, u, v)

        return self._delta_tdb_tt

    def set_delta_tdb_tt(self, val):
        self._delta_tdb_tt = self._match_len(val)

    def __len__(self):
        return len(self._time.jd1)

    def __sub__(self, other):
        self_tai = self.tai
        if not isinstance(other, Time):
            _unsupported_op_type(self, other)

        other_tai = other.tai
        jd1 = self_tai.jd1 - other_tai.jd1
        jd2 = self_tai.jd2 - other_tai.jd2

        # T      - Tdelta = T
        # Tdelta - Tdelta = Tdelta
        # T      - T      = Tdelta
        # Tdelta - T      = error
        self_delta = isinstance(self, TimeDelta)
        other_delta = isinstance(other, TimeDelta)
        self_time = not self_delta  # only 2 possibilities
        other_time = not other_delta
        if (self_delta and other_delta) or (self_time and other_time):
            return TimeDelta(jd1, jd2, format='jd')
        elif (self_time and other_delta):
            self_tai._time.jd1 = jd1
            self_tai._time.jd2 = jd2
            return getattr(self_tai, self.scale)
        else:
            _unsupported_op_type(self, other)

    def __add__(self, other):
        self_tai = self.tai
        if not isinstance(other, Time):
            _unsupported_op_type(self, other)

        other_tai = other.tai
        jd1 = self_tai.jd1 + other_tai.jd1
        jd2 = self_tai.jd2 + other_tai.jd2

        # T      + Tdelta = T
        # Tdelta + Tdelta = Tdelta
        # T      + T      = error
        # Tdelta + T      = T
        self_delta = isinstance(self, TimeDelta)
        other_delta = isinstance(other, TimeDelta)
        self_time = not self_delta  # only 2 possibilities
        other_time = not other_delta
        if (self_delta and other_delta):
            return TimeDelta(jd1, jd2, format='jd')
        elif (self_time and other_delta) or (self_delta and other_time):
            tai = self_tai if self_time else other_tai
            scale = self.scale if self_time else other.scale
            tai._time.jd1 = jd1
            tai._time.jd2 = jd2
            return getattr(tai, scale)
        else:
            _unsupported_op_type(self, other)


class TimeDelta(Time):
    """Represent the time difference between two times.

    A Time object is initialized with one or more times in the ``val``
    argument.  The input times in ``val`` must conform to the specified
    ``format`` and must correspond to the specified time ``scale``.  The
    optional ``val2`` time input should be supplied only for numeric input
    formats (e.g. JD) where very high precision (better than 64-bit precision)
    is required.

    Parameters
    ----------
    val : numpy ndarray, list, str, or number
        Data to initialize table.
    val2 : numpy ndarray, list, str, or number; optional
        Data to initialize table.
    format : str, optional
        Format of input value(s)
    scale : str, optional
        Time scale of input value(s)
    lat : float, optional
        Earth latitude of observer
    lon : float, optional
        Earth longitude of observer
    """
    def __init__(self, val, val2=None, format=None, scale=None):
        self.SCALES = TIME_DELTA_SCALES
        self.FORMATS = TIME_DELTA_FORMATS
        self._init_from_vals(val, val2, format, 'tai')


class TimeFormat(object):
    """
    Base class for time representations.

    Parameters
    ----------
    val1 : numpy ndarray, list, str, or number
        Data to initialize table.
    val2 : numpy ndarray, list, str, or number; optional
        Data to initialize table.
    scale : str
        Time scale of input value(s)
    precision : int
        Precision for seconds as floating point
    in_subfmt : str
        Select subformat for inputting string times
    out_subfmt : str
        Select subformat for outputting string times
    from_jd : bool
        If true then val1, val2 are jd1, jd2
    """
    def __init__(self, val1, val2, scale, precision,
                 in_subfmt, out_subfmt, from_jd=False):
        if hasattr(self.__class__, 'scale'):
            # This format class has a required time scale
            cls_scale = getattr(self.__class__, 'scale')
            if (scale is not None and scale != cls_scale):
                raise ValueError('Class {0} requires scale={1} or None'
                                 .format(self.__class__.__name__, cls_scale))
        else:
            self.scale = scale
        self.precision = precision
        self.in_subfmt = in_subfmt
        self.out_subfmt = out_subfmt
        self.n_times = len(val1)
        if len(val1) != len(val2):
            raise ValueError('Input val1 and val2 must match in length')

        if from_jd:
            self.jd1 = val1
            self.jd2 = val2
        else:
            self._check_val_type(val1, val2)
            self.set_jds(val1, val2)

    def _check_val_type(self, val1, val2):
        if val1.dtype.type != np.double or val2.dtype.type != np.double:
            raise TypeError('Input values for {0} class must be doubles'
                             .format(self.name))

    def set_jds(self, val1, val2):
        raise NotImplementedError

    @property
    def vals(self):
        raise NotImplementedError


class TimeJD(TimeFormat):
    name = 'jd'

    def set_jds(self, val1, val2):
        self.jd1 = val1
        self.jd2 = val2

    @property
    def vals(self):
        return self.jd1 + self.jd2


class TimeMJD(TimeFormat):
    name = 'mjd'

    def set_jds(self, val1, val2):
        # XXX - this routine and vals should be Cythonized to follow the SOFA
        # convention of preserving precision by adding to the larger of the two
        # values in a vectorized operation.  But in most practical cases the
        # first one is probably biggest.
        self.jd1 = val1 + MJD_ZERO
        self.jd2 = val2

    @property
    def vals(self):
        return (self.jd1 - MJD_ZERO) + self.jd2


class TimeFromEpoch(TimeFormat):
    """Base class for times that represent the interval from a particular
    epoch as a floating point multiple of a unit time interval (e.g. seconds
    or days).
    """
    def __init__(self, val1, val2, scale, precision,
                 in_subfmt, out_subfmt, from_jd=False):
        epoch = Time(self.epoch_val, self.epoch_val2, scale=self.epoch_scale,
                     format=self.epoch_format)
        self.epoch = getattr(epoch, self.scale)
        super(TimeFromEpoch, self).__init__(val1, val2, scale, precision,
                                            in_subfmt, out_subfmt, from_jd)

    def set_jds(self, val1, val2):
        self.jd1 = self.epoch.jd1 + val2 * self.unit
        self.jd2 = self.epoch.jd2 + val1 * self.unit

    @property
    def vals(self):
        return ((self.jd1 - self.epoch.jd1) +
                (self.jd2 - self.epoch.jd2)) / self.unit


class TimeUnix(TimeFromEpoch):
    """Unix time: seconds from 1970-01-01 00:00:00 UTC.

    NOTE: this quantity is not exactly unix time and differs from the strict
    POSIX definition by up to 1 second on days with a leap second.  POSIX
    unix time actually jumps backward by 1 second at midnight on leap second
    days while this class value is monotonically increasing at 86400 seconds
    per UTC day.
    """
    name = 'unix'
    unit = 1.0 / SECS_PER_DAY  # in days (1 day == 86400 seconds)
    epoch_val = '1970-01-01 00:00:00'
    epoch_val2 = None
    epoch_scale = 'utc'
    epoch_format = 'iso'
    scale = 'utc'


class TimeCxcSec(TimeFromEpoch):
    """Chandra X-ray Center seconds from 1998-01-01 00:00:00 TT.
    """
    name = 'cxcsec'
    unit = 1.0 / SECS_PER_DAY  # in days (1 day == 86400 seconds)
    epoch_val = '1998-01-01 00:00:00'
    epoch_val2 = None
    epoch_scale = 'tt'
    epoch_format = 'iso'
    scale = 'tai'


class TimeString(TimeFormat):
    """Base class for string-like time represetations.

    This class assumes that anything following the last decimal point to the
    right is a fraction of a second.

    This is a reference implementation can be made much faster with effort.
    """

    def _check_val_type(self, val1, val2):
        if val1.dtype.kind != 'S':
            raise TypeError('Input values for {0} class must be strings'
                             .format(self.name))
            # Note: don't care about val2 for these classes

    def set_jds(self, val1, val2):
        """
        Parse the time strings contained in val1 and set jd1, jd2.
        """
        iy = np.empty(self.n_times, dtype=np.intc)
        im = np.empty(self.n_times, dtype=np.intc)
        id = np.empty(self.n_times, dtype=np.intc)
        ihr = np.empty(self.n_times, dtype=np.intc)
        imin = np.empty(self.n_times, dtype=np.intc)
        dsec = np.empty(self.n_times, dtype=np.double)

        # Select subformats based on current self.in_subfmt
        subfmts = self._select_subfmts(self.in_subfmt)

        for i, timestr in enumerate(val1):
            # Assume that anything following "." on the right side is a
            # floating fraction of a second.
            try:
                idot = timestr.rindex('.')
            except:
                fracsec = 0.0
            else:
                timestr, fracsec = timestr[:idot], timestr[idot:]
                fracsec = float(fracsec)

            for _, strptime_fmt, _ in subfmts:
                try:
                    tm = time.strptime(timestr, strptime_fmt)
                except ValueError:
                    pass
                else:
                    iy[i] = tm.tm_year
                    im[i] = tm.tm_mon
                    id[i] = tm.tm_mday
                    ihr[i] = tm.tm_hour
                    imin[i] = tm.tm_min
                    dsec[i] = tm.tm_sec + fracsec
                    break
            else:
                raise ValueError('Time {0} does not match {1} format'
                                 .format(timestr, self.name))

        self.jd1, self.jd2 = sofa_time.dtf_jd(self.scale,
                                              iy, im, id, ihr, imin, dsec)

    def str_kwargs(self):
        """Generator that yields a dict of values corresponding to the
        calendar date and time for the internal JD values.
        """
        iys, ims, ids, ihmsfs = sofa_time.jd_dtf(self.scale.upper(),
                                                 self.precision,
                                                 self.jd1, self.jd2)

        # Get the str_fmt element of the first allowed output subformat
        _, _, str_fmt = self._select_subfmts(self.out_subfmt)[0]

        if '{yday:' in str_fmt:
            from datetime import datetime
            has_yday = True
        else:
            has_yday = False
            yday = None

        for iy, im, id, ihmsf in itertools.izip(iys, ims, ids, ihmsfs):
            ihr, imin, isec, ifracsec = ihmsf
            if has_yday:
                yday = datetime(iy, im, id).timetuple().tm_yday

            yield {'year': int(iy), 'mon': int(im), 'day': int(id),
                   'hour': int(ihr), 'min': int(imin), 'sec': int(isec),
                   'fracsec': int(ifracsec), 'yday': yday}

    @property
    def vals(self):
        # Select the first available subformat based on current
        # self.out_subfmt
        subfmts = self._select_subfmts(self.out_subfmt)
        _, _, str_fmt = subfmts[0]

        # XXX ugly hack, fix
        if self.precision > 0 and str_fmt.endswith('{sec:02d}'):
            str_fmt += '.{fracsec:0' + str(self.precision) + 'd}'

        # Try to optimize this later.  Can't pre-allocate because length of
        # output could change, e.g. year rolls from 999 to 1000.
        outs = []
        for kwargs in self.str_kwargs():
            outs.append(str_fmt.format(**kwargs))

        return np.array(outs)

    def _select_subfmts(self, pattern):
        """Return a list of subformats where name matches ``pattern`` using
        fnmatch.
        """
        from fnmatch import fnmatchcase
        subfmts = [x for x in self.subfmts if fnmatchcase(x[0], pattern)]
        if len(subfmts) == 0:
            raise ValueError('No subformats match {0}'.format(pattern))
        return subfmts


class TimeISO(TimeString):
    name = 'iso'
    subfmts = (('date_hms',
                '%Y-%m-%d %H:%M:%S',
                # XXX To Do - use strftime for output ??
                '{year:d}-{mon:02d}-{day:02d} {hour:02d}:{min:02d}:{sec:02d}'),
               ('date_hm',
                '%Y-%m-%d %H:%M',
                '{year:d}-{mon:02d}-{day:02d} {hour:02d}:{min:02d}'),
               ('date',
                '%Y-%m-%d',
                '{year:d}-{mon:02d}-{day:02d}'))


class TimeISOT(TimeString):
    name = 'isot'
    subfmts = (('date_hms',
                '%Y-%m-%dT%H:%M:%S',
                '{year:d}-{mon:02d}-{day:02d}T{hour:02d}:{min:02d}:{sec:02d}'),
               ('date_hm',
                '%Y-%m-%dT%H:%M',
                '{year:d}-{mon:02d}-{day:02d}T{hour:02d}:{min:02d}'),
               ('date',
                '%Y-%m-%d',
                '{year:d}-{mon:02d}-{day:02d}'))


class TimeYearDayTime(TimeString):
    name = 'yday'
    subfmts = (('date_hms',
                '%Y:%j:%H:%M:%S',
                '{year:d}:{yday:03d}:{hour:02d}:{min:02d}:{sec:02d}'),
               ('date_hm',
                '%Y:%j:%H:%M',
                '{year:d}:{yday:03d}:{hour:02d}:{min:02d}'),
               ('date',
                '%Y:%j',
                '{year:d}:{yday:03d}'))


class TimeEpochDate(TimeFormat):
    """Base class for support Besselian and Julian epoch dates (e.g.
    B1950.0 or J2000.0 etc).
    """
    def set_jds(self, val1, val2):
        epoch_to_jd = getattr(sofa_time, self.epoch_to_jd)
        self.jd1, self.jd2 = epoch_to_jd(val1 + val2)

    @property
    def vals(self):
        jd_to_epoch = getattr(sofa_time, self.jd_to_epoch)
        return jd_to_epoch(self.jd1, self.jd2)


class TimeBesselianEpoch(TimeEpochDate):
    """Besselian Epoch year"""
    name = 'byear'
    epoch_to_jd = 'besselian_epoch_jd'
    jd_to_epoch = 'jd_besselian_epoch'


class TimeJulianEpoch(TimeEpochDate):
    """Julian Epoch year"""
    name = 'jyear'
    epoch_to_jd = 'julian_epoch_jd'
    jd_to_epoch = 'jd_julian_epoch'


class TimeDeltaFormat(TimeFormat):
    """
    Base class for time delta represenations.
    """
    pass


class TimeDeltaSec(TimeDeltaFormat):
    name = 'sec'

    def set_jds(self, val1, val2):
        self.jd1 = val1 / SECS_PER_DAY
        self.jd2 = val2 / SECS_PER_DAY

    @property
    def vals(self):
        return (self.jd1 + self.jd2) * SECS_PER_DAY


class TimeDeltaJD(TimeDeltaFormat):
    name = 'jd'

    def set_jds(self, val1, val2):
        self.jd1 = val1
        self.jd2 = val2

    @property
    def vals(self):
        return self.jd1 + self.jd2


# Set module constant with names of all available time formats
_module = sys.modules[__name__]
for name in dir(_module):
    val = getattr(_module, name)
    try:
        is_timeformat = issubclass(val, TimeFormat)
        is_timedeltaformat = issubclass(val, TimeDeltaFormat)
    except:
        pass
    else:
        if hasattr(val, 'name'):
            if is_timedeltaformat:
                TIME_DELTA_FORMATS[val.name] = val
            elif is_timeformat:
                TIME_FORMATS[val.name] = val


def _make_1d_array(val):
    val = np.asarray(val)
    val_ndim = val.ndim  # remember original ndim
    if val.ndim == 0:
        val = np.asarray([val])
    elif val_ndim > 1:
        # Maybe lift this restriction later to allow multi-dim in/out?
        raise TypeError('Input val must be zero or one dimensional')

    # Allow only string or float arrays as input (XXX datetime later...)
    if val.dtype.kind == 'i':
        val = np.asarray(val, dtype=np.float64)

    return val, val_ndim

def _unsupported_op_type(left, right):
    raise TypeError("unsupported operand type(s) for -: "
                    "'{0}' and '{1}'".format(left.__class__.__name__,
                                             right.__class__.__name__))
