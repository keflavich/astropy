# Licensed under a 3-clause BSD style license - see LICENSE.rst
#This module implements the base NDData class.

__all__ = ['NDData']

import numpy as np

class NDData(object):
    """Superclass for Astropy data.

    `NDData` provides a superclass for all array-based data. The key
    distinction from raw numpy arrays is the presence of additional metadata
    like error arrays, bad pixel masks, or coordinates.

    Parameters
    ----------
    data : `~numpy.ndarray`
        The actual data contained in this `NDData` object.
    error : `~numpy.ndarray`, optional
        Error of the data. This should be interpreted as a standard
        deviation-type error (e.g. square root of the variance).

         .. warning::
             The physical interpretation of the `error` array may change in the
             future, as it has not been intensively discussed. For now assume
             the above description holds, using an `error` property if
             necessary, but feel free to use the most convinient internal
             representation in subclasses

    mask : `~numpy.ndarray`, optional
        Masking of the data; True where the array is *valid*, False where it is
        *invalid*.
    wcs : undefined, optional
        WCS-object containing the world coordinate system for the data.

        .. warning::
            This is not yet defind because the discussion of how best to
            represent this class's WCS system generically is still under
            consideration. For now just leave it as None

    meta : `dict`-like object, optional
        Metadata for this object.  "Metadata" here means all information that
        is included with this object but not part of the python representation
        of this particular object.  e.g., exposure times, instrument or
        telescope status information, observatory location information, etc.
        Basically the same kind of stuff you would typcially find in a FITS
        header.
    units : undefined, optional
        Description of the units of the data.

        .. warning::
            The units scheme is under development. For now, just supply a
            string when relevant - the units system will likely be compatible
            with providing strings to initialize itself.

    """
    def __init__(self, data, error=None, mask=None, wcs=None, meta=None,
                 units=None):
        self.data = data
        self.error = error
        self.mask = mask
        self._validate_mask_and_error()

        self.wcs = wcs
        self.units = units
        if meta is None:
            self.meta = {}
        else:
            self.meta = dict(meta)  # makes a *copy* of the passed-in meta

    def _validate_mask_and_error(self):
        """
        Raises ValueError if they don't match
        """
        try:
            if self.error is not None:
                np.broadcast(self.data, self.error)
            errmatch = True
        except ValueError:
            errmatch = False
        try:
            if self.mask is not None:
                np.broadcast(self.data, self.mask)
            maskmatch = True
        except ValueError:
            maskmatch = False

        if not errmatch and not maskmatch:
            raise ValueError('NDData error and mask do not match data')
        elif not errmatch:
            raise ValueError('NDData error does not match data')
        elif not maskmatch:
            raise ValueError('NDData mask does not match data')
