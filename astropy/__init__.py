# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
Astropy is a package intended to contain core functionality and some
common tools needed for performing astronomy and astrophysics research with
Python. It also provides an index for other astronomy packages and tools for
managing them.
"""


try:
    from astropy.version import version as __version__
except ImportError:
    # TODO: Issue a warning...
    __version__ = ''
# The version number can be found in the "version" variable of version.py



from .tests.helper import run_tests as test
