#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012 the authors. See the file "AUTHORS" for a complete list.

from __future__ import absolute_import, print_function

import threading
import logging
from looping import tulip


# Allow this module to be compiled even if pyev is not installed
try:
    import pyev
    available = True
except ImportError:
    available = False


def call_dcall(dcall):
    try:
        if dcall.kwds:
            dcall.callback(*dcall.args, **dcall.kwds)
        else:
            dcall.callback(*dcall.args)
    except Exception:
        logging.exception('Exception in callback %s %r',
                           dcall.callback, dcall.args)


def watcher_callback(watcher, events):
    dcall = watcher.data
    if not dcall:
        return
    call_dcall(dcall)
    if not dcall.repeat:
        dcall.cancel()


class DelayedCall(tulip.DelayedCall):
    """DelayedCall that stores a generic watcher."""

    def __init__(self, watcher, callback, args, kwds=None, repeat=True):
        super(DelayedCall, self).__init__(None, repeat, callback, args, kwds)
        self.watcher = watcher
        self.watcher.data = self

    def cancel(self):
        super(DelayedCall, self).cancel()
        self.watcher.stop()
        self.watcher.data = None


class EventLoop(object):
    """An EventLoop based on libev (using pyev)."""

    default_loop = None

    def __init__(self, loop=None):
        if not available:
            raise ImportError('pyev is not available on this system')
        # Cache the default loop in our class to suppress a warning from
        # pyev when default_loop() is called multiple times.
        if loop is None:
            loop = self.default_loop
            if loop is None:
                type(self).default_loop = pyev.default_loop()
            loop = self.default_loop
        self.loop = loop
        # libev support multiple callbacks per file descriptor, however
        # the EventLoop API doesn't (remove_reader/writer take an FD
        # instead of a DelayedCall instance).
        # Therefore we keep two maps mapping back FDs to a DelayedCall
        self.readers = {}  # {fd: dcall, ...}
        self.writers = {}  # {fd: dcall, ...}

    def add_reader(self, fd, callback, *args):
        dcall = self.readers.get(fd)
        if dcall:
            raise ValueError('cannot add multiple readers per fd')
        io = pyev.Io(fd, pyev.EV_READ, self.loop, watcher_callback)
        dcall = DelayedCall(io, callback, args)
        self.readers[fd] = dcall
        io.start()
        return dcall

    def add_writer(self, fd, callback, *args):
        dcall = self.writers.get(fd)
        if dcall:
            raise ValueError('cannot add multiple writers per fd')
        io = pyev.Io(fd, pyev.EV_WRITE, self.loop, watcher_callback)
        dcall = DelayedCall(io, callback, args)
        self.writers[fd] = dcall
        io.start()
        return dcall

    def remove_reader(self, fd):
        dcall = self.readers.get(fd)
        if not dcall:
            raise ValueError('file descriptor not registered for reading')
        dcall.cancel()
        del self.readers[fd]

    def remove_writer(self, fd):
        dcall = self.writers.get(fd)
        if not dcall:
            raise ValueError('file descriptor not registered for writing')
        dcall.cancel()
        del self.writers[fd]

    def call_soon(self, repeat, callback, *args):
        prep = pyev.Prepare(self.loop, watcher_callback)
        dcall = DelayedCall(prep, callback, args, not repeat)
        prep.start()
        return dcall

    def call_later(self, when, repeat, callback, *args):
        if when >= 10000000:
            when -= self.loop.now()
        if when <= 0:
            raise ValueError('illegal timeout')
        timer = pyev.Timer(when, repeat, self.loop, watcher_callback)
        dcall = DelayedCall(timer, callback, args, not repeat)
        timer.start()
        return dcall

    def run_once(self, timeout=None):
        if timeout is not None:
            def stop_loop(watcher, events):
                pass
            timer = pyev.Timer(timeout, 0, self.loop, stop_loop)
            timer.start()
        self.loop.start(pyev.EVRUN_ONCE)
        if timeout is not None:
            timer.stop()

    def run(self):
        self.loop.start()
