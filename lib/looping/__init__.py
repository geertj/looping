#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the authors. See the file "AUTHORS" for a complete
# list.

from __future__ import absolute_import, print_function

from .events import *

try:
    from .pyuv import PyUVEventLoop
except ImportError:
    pass

try:
    from .pyside import PySideEventLoop
except ImportError:
    pass
