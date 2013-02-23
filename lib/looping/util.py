#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the authors. See the file "AUTHORS" for a complete
# list.

import os
import sys
import errno
import warnings

try:
    import fcntl
except ImportError:
    fcntl = None

# Errno values indicating the socket isn't ready for I/O just yet.
TRYAGAIN = frozenset((errno.EAGAIN, errno.EWOULDBLOCK, errno.EINPROGRESS))
if sys.platform == 'win32':
    TRYAGAIN = frozenset(list(TRYAGAIN) + [errno.WSAEWOULDBLOCK])

def setblocking(fd, blocking):
    """Set the O_NONBLOCK flag for a file descriptor. Availability: Unix."""
    if not fcntl:
        warnings.warn('setblocking() not supported on Windows')
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    if blocking:
        flags |= os.O_NONBLOCK
    else:
        flags &= ~os.O_NONBLOCK
    fcntl.fcntl(fd, fcntl.F_SETFL, flags)
