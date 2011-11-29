# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
Simple utility functions and bug fixes for compatibility with all supported
versions of Python.  This module should generally not be used directly, as 
everything in `__all__` will be imported into `astropy.utils.compat` and can
be accessed from there.
"""

from __future__ import absolute_import

from sys import version_info

__all__ = ['patched_getmodule','inspect_getmodule']

def patched_getmodule(object, _filename=None):
    """Return the module an object was defined in, or None if not found.
    
    This replicates the functionality of the stdlib `inspect.getmodule` 
    function but includes a fix for a bug present in Python 3.1 and 3.2.
    """    
    #these imports mock up what would otherwise have been in inspect
    import sys
    import os
    from inspect import modulesbyfile,_filesbymodname,getabsfile,ismodule
    
    if ismodule(object):
        return object
    if hasattr(object, '__module__'):
        return sys.modules.get(object.__module__)
    # Try the filename to modulename cache
    if _filename is not None and _filename in modulesbyfile:
        return sys.modules.get(modulesbyfile[_filename])
    # Try the cache again with the absolute file name
    try:
        file = getabsfile(object, _filename)
    except TypeError:
        return None
    if file in modulesbyfile:
        return sys.modules.get(modulesbyfile[file])
    # Update the filename to module name cache and check yet again
    # Copy sys.modules in order to cope with changes while iterating
    # This is where the fix is made - the adding of the "list" call:
    for modname, module in list(sys.modules.items()):
        if ismodule(module) and hasattr(module, '__file__'):
            f = module.__file__
            if f == _filesbymodname.get(modname, None):
                # Have already mapped this module, so skip it
                continue
            _filesbymodname[modname] = f
            f = getabsfile(module)
            # Always map to the name the module knows itself by
            modulesbyfile[f] = modulesbyfile[
                os.path.realpath(f)] = module.__name__
    if file in modulesbyfile:
        return sys.modules.get(modulesbyfile[file])
    # Check the main module
    main = sys.modules['__main__']
    if not hasattr(object, '__name__'):
        return None
    if hasattr(main, object.__name__):
        mainobject = getattr(main, object.__name__)
        if mainobject is object:
            return main
    # Check builtins
    builtin = sys.modules['builtins']
    if hasattr(builtin, object.__name__):
        builtinobject = getattr(builtin, object.__name__)
        if builtinobject is object:
            return builtin

#This assigns the stdlib inspect.getmodule to the variable name 
#`inspect_getmodule` if it's not buggy, and uses the matched version if it is.
if version_info[0]<3 or version_info[1]>2:
    #in 2.x everythig is fine, as well as >=3.3
    from inspect import getmodule as inspect_getmodule
else:
    inspect_getmodule = patched_getmodule
    