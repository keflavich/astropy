# Licensed under a 3-clause BSD style license - see LICENSE.rst
from __future__ import division

import imp

from distutils import log

"""
Utilities for generating the version string for Astropy (or an affiliated
package) and the version.py module, which contains version info for the
package.

Within the generated astropy.version module, the `major`, `minor`, and `bugfix`
variables hold the respective parts of the version number (bugfix is '0' if
absent). The `release` variable is True if this is a release, and False if this
is a development version of astropy. For the actual version string, use::

    from astropy.version import version

or::

    from astropy import __version__

"""


def _version_split(version):
    """
    Split a version string into major, minor, and bugfix numbers (with bugfix
    optional, defaulting to 0).
    """

    versplit = version.split('.dev')[0].split('.')
    major = int(versplit[0])
    minor = int(versplit[1])
    bugfix = 0 if len(versplit) < 3 else int(versplit[2])
    return major, minor, bugfix


def _update_git_devstr(version, path=None):
    """
    Updates the git revision string if and only if the path is being imported
    directly from a git working copy.  This ensures that the revision number in
    the version string is accurate.
    """

    try:
        # Quick way to determine if we're in git or not - returns '' if not
        devstr = get_git_devstr(sha=True, show_warning=False, path=path)
    except OSError:
        return version

    if not devstr:
        # Probably not in git so just pass silently
        return version

    if 'dev' in version:  # update to the current git revision
        version_base = version.split('.dev', 1)[0]
        devstr = get_git_devstr(sha=False, show_warning=False, path=path)

        return version_base + '.dev' + devstr
    else:
        #otherwise it's already the true/release version
        return version


def get_git_devstr(sha=False, show_warning=True, path=None):
    """
    Determines the number of revisions in this repository.

    Parameters
    ----------
    sha : bool
        If True, the full SHA1 hash will be returned. Otherwise, the total
        count of commits in the repository will be used as a "revision
        number".

    show_warning : bool
        If True, issue a warning if git returns an error code, otherwise errors
        pass silently.

    path : str or None
        If a string, specifies the directory to look in to find the git
        repository.  If None, the location of the file this function is in
        is used to infer the git repository location.  If given a filename it
        uses the directory containing that file.

    Returns
    -------
    devversion : str
        Either a string with the revsion number (if `sha` is False), the
        SHA1 hash of the current commit (if `sha` is True), or an empty string
        if git version info could not be identified.

    """

    import os
    from subprocess import Popen, PIPE
    from warnings import warn
    from .utils import find_current_module

    if path is None:
        try:
            mod = find_current_module(1, finddiff=True)
            path = os.path.abspath(mod.__file__)
        except ValueError:
            path = __file__
    if not os.path.isdir(path):
        path = os.path.abspath(os.path.split(path)[0])

    if sha:
        cmd = 'rev-parse'  # Faster for getting just the hash of HEAD
    else:
        cmd = 'rev-list'

    try:
        p = Popen(['git', cmd, 'HEAD'], cwd=path,
                  stdout=PIPE, stderr=PIPE, stdin=PIPE)
        stdout, stderr = p.communicate()
    except OSError as e:
        if show_warning:
            warn('Error running git: ' + str(e))
        return ''

    if p.returncode == 128:
        if show_warning:
            warn('No git repository present! Using default dev version.')
        return ''
    elif p.returncode != 0:
        if show_warning:
            warn('Git failed while determining revision count: ' + stderr)
        return ''

    if sha:
        return stdout.decode('utf-8')[:40]
    else:
        nrev = stdout.decode('utf-8').count('\n')
        return  str(nrev)


# This is used by setup.py to create a new version.py - see that file for
# details
_frozen_version_py_template = """
# Autogenerated by {packagename}'s setup.py on {timestamp}

from astropy.version_helper import _update_git_devstr, get_git_devstr

version = _update_git_devstr({verstr!r})
githash = get_git_devstr(sha=True, show_warning=False)

major = {major}
minor = {minor}
bugfix = {bugfix}

release = {rel}
debug = {debug}

try:
    from astropy._compiler import compiler
except ImportError:
    compiler = "unknown"
"""[1:]


def _get_version_py_str(packagename, version, release, debug):

    import datetime

    timestamp = str(datetime.datetime.now())
    major, minor, bugfix = _version_split(version)
    if packagename.lower() == 'astropy':
        packagename = 'Astropy'
    else:
        packagename = 'Astropy-affiliated package ' + packagename
    return _frozen_version_py_template.format(packagename=packagename,
                                              timestamp=timestamp,
                                              verstr=version,
                                              major=major,
                                              minor=minor,
                                              bugfix=bugfix,
                                              rel=release, debug=debug)


def generate_version_py(packagename, version, release, debug=None):
    """Regenerate the version.py module if necessary."""

    import os
    import sys

    try:
        version_module = __import__(packagename + '.version',
                                    fromlist=['version', 'release', 'debug'])
        current_version = version_module.version
        current_release = version_module.release
        current_debug = version_module.debug
    except ImportError:
        version_module = None
        current_version = None
        current_release = None
        current_debug = None

    if debug is None:
        # Keep whatever the current value is, if it exists
        debug = bool(current_debug)

    version_py = os.path.join(packagename, 'version.py')

    if (current_version != version or current_release != release or
        current_debug != debug):
        if '-q' not in sys.argv and '--quiet' not in sys.argv:
            log.set_threshold(log.INFO)
        log.info('Freezing version number to {0}'.format(version_py))

        with open(version_py, 'w') as f:
            # This overwrites the actual version.py
            f.write(_get_version_py_str(packagename, version, release, debug))

        if version_module:
            imp.reload(version_module)
