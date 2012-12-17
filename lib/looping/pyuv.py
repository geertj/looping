#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012 the authors. See the file "AUTHORS" for a complete list.

from __future__ import absolute_import, print_function

from looping import tulip
import threading
import logging


# Allow this module to be compiled even if pyuv is not installed
try:
    import pyuv
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


def poll_callback(handle, events, error):
    if error:
        return
    if events & pyuv.UV_READABLE and handle.reader:
        call_dcall(handle.reader)
    if events & pyuv.UV_WRITABLE and handle.writer:
        call_dcall(handle.writer)


class Reader(tulip.DelayedCall):
    """Use to multiplex a pyuv.Poll into an independent reader
    and writer."""

    def __init__(self, poll, callback, args, kwds=None):
        super(Reader, self).__init__(None, None, callback, args, kwds)
        self.poll = poll
        self.poll.reader = self
        self.poll.events |= pyuv.UV_READABLE

    def cancel(self):
        super(Reader, self).cancel()
        self.poll.events &= ~pyuv.UV_READABLE
        if self.poll.events == 0:
            self.poll.close()


class Writer(tulip.DelayedCall):
    """Use to multiplex a pyuv.Poll into an independent reader
    and writer."""

    def __init__(self, poll, callback, args, kwds=None):
        super(Writer, self).__init__(None, None, callback, args, kwds)
        self.poll = poll
        self.poll.writer = self
        self.poll.events |= pyuv.UV_WRITABLE

    def cancel(self):
        super(Writer, self).cancel()
        self.poll.events &= ~pyuv.UV_WRITABLE
        if self.poll.events == 0:
            self.poll.close()


def handle_callback(handle):
    call_dcall(handle.dcall)
    if handle.single_shot:
        handle.close()


class Handle(tulip.DelayedCall):
    """DelayedCall that stores a generic handle.

    Used for Prepare and Timer handles.
    """

    def __init__(self, handle, callback, args, kwds=None, single_shot=False):
        super(Handle, self).__init__(None, None, callback, args, kwds)
        self.handle = handle
        self.handle.dcall = self
        self.handle.single_shot = single_shot

    def cancel(self):
        super(Handle, self).cancel()
        self.handle.close()


class EventLoop(object):
    """An EventLoop based on libuv (using pyuv)."""

    def __init__(self, loop=None):
        if not available:
            raise ImportError('pyuv is not available on this system')
        self.loop = loop or pyuv.Loop.default_loop()
        # libuv does not support multiple callbacks per file descriptor.
        # Therefore we need to keep an map, and we also need to multiplex
        # readers and writers for the same FD onto one Poll instance.
        self.fdmap = {}  # { fd: poll, ... }

    def _new_poll(self, fd):
        poll = pyuv.Poll(self.loop, fd)
        poll.reader = None
        poll.writer = None
        poll.events = 0
        return poll

    def add_reader(self, fd, callback, *args):
        poll = self.fdmap.get(fd)
        if poll and poll.reader:
            raise ValueError('cannot add multiple readers per fd')
        elif not poll:
            poll = self._new_poll(fd)
            self.fdmap[fd] = poll
        dcall = Reader(poll, callback, args)
        poll.start(poll.events, poll_callback)
        return dcall

    def add_writer(self, fd, callback, *args):
        poll = self.fdmap.get(fd)
        if poll and poll.writer:
            raise ValueError('cannot add multiple writers per fd')
        elif not poll:
            poll = self._new_poll(fd)
            self.fdmap[fd] = poll
        dcall = Writer(poll, callback, args)
        poll.start(poll.events, poll_callback)
        return dcall

    def remove_reader(self, fd):
        poll = self.fdmap.get(fd)
        if not poll or not poll.reader:
            raise ValueError('file descriptor not registered for reading')
        poll.reader.cancel()
        if poll.closed:
            del self.fdmap[fd]

    def remove_writer(self, fd):
        poll = self.fdmap.get(fd)
        if not poll or not poll.writer:
            raise ValueError('file descriptor not registered for writing')
        poll.writer.cancel()
        if poll.closed:
            del self.fdmap[fd]

    def call_soon(self, repeat, callback, *args):
        prep = pyuv.Prepare(self.loop)
        dcall = Handle(prep, callback, args, single_shot=not repeat)
        prep.start(handle_callback)
        return dcall

    def call_later(self, when, repeat, callback, *args):
        timer = pyuv.Timer(self.loop)
        if when >= 10000000:
            when -= self.loop.now()
        if when <= 0:
            raise ValueError('illegal timeout')
        dcall = Handle(timer, callback, args, single_shot=not repeat)
        timer.start(handle_callback, when, repeat)
        return dcall

    def run_once(self, timeout=None):
        if timeout is not None:
            timer = pyuv.Timer(self.loop)
            def stop_loop(handle):
                pass
            timer.start(stop_loop, timeout, 0)
        self.loop.run_once()
        if timeout is not None:
            timer.close()

    def run(self):
        self.loop.run()
