#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012 the authors. See the file "AUTHORS" for a complete list.

from __future__ import absolute_import, print_function

import logging
import pyev
from . import events


class Handler(events.Handler):
    """Handler that stores a generic libev watcher."""

    def __init__(self, watcher, callback, args, kwds=None, single_shot=False):
        super(Handler, self).__init__(None, callback, args, kwds)
        self.watcher = watcher
        self.single_shot = single_shot

    def cancel(self):
        super(Handler, self).cancel()
        self.watcher.stop()
        self.watcher = None

    def __call__(self, *ignored):
        if self.cancelled:
            return
        try:
            if self.kwds:
                self.callback(*self.args, **self.kwds)
            else:
                self.callback(*self.args)
        except Exception:
            logging.exception('Exception in callback %s %r',
                               self.callback, self.args)
        if self.single_shot:
            self.cancel()


class EventLoop(events.EventLoop):
    """An EventLoop based on libev (using pyev)."""

    default_loop = None

    def __init__(self, loop=None):
        super(EventLoop, self).__init__()
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
        # instead of a Handler instance).
        # Therefore we keep two maps mapping back FDs to a Handler
        self.readers = {}  # {fd: handler, ...}
        self.writers = {}  # {fd: handler, ...}

    def add_reader(self, fd, callback, *args):
        handler = self.readers.get(fd)
        if handler:
            raise ValueError('cannot add multiple readers per fd')
        handler = Handler(None, callback, args)
        io = pyev.Io(fd, pyev.EV_READ, self.loop, handler)
        handler.watcher = io
        self.readers[fd] = handler
        io.start()
        return handler

    def add_writer(self, fd, callback, *args):
        handler = self.writers.get(fd)
        if handler:
            raise ValueError('cannot add multiple writers per fd')
        handler = Handler(None, callback, args)
        io = pyev.Io(fd, pyev.EV_WRITE, self.loop, handler)
        handler.watcher = io
        self.writers[fd] = handler
        io.start()
        return handler

    def remove_reader(self, fd):
        handler = self.readers.get(fd)
        if not handler:
            raise ValueError('file descriptor not registered for reading')
        handler.cancel()
        del self.readers[fd]

    def remove_writer(self, fd):
        handler = self.writers.get(fd)
        if not handler:
            raise ValueError('file descriptor not registered for writing')
        handler.cancel()
        del self.writers[fd]

    def call_soon(self, callback, *args):
        handler = Handler(None, callback, args, True)
        prep = pyev.Prepare(self.loop, handler)
        handler.watcher = prep
        prep.start()
        return handler

    def call_later(self, when, callback, *args):
        handler = Handler(None, callback, args, True)
        timer = pyev.Timer(when, 0, self.loop, handler)
        handler.watcher = timer
        timer.start()
        return handler

    def call_repeatedly(self, interval, callback, *args):
        handler = Handler(None, callback, args)
        timer = pyev.Timer(interval, interval, self.loop, handler)
        handler.watcher = timer
        timer.start()
        return handler

    def call_every_iteration(self, callback, *args):
        handler = Handler(None, callback, args)
        prep = pyev.Prepare(self.loop, handler)
        handler.watcher = prep
        prep.start()
        return handler

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
