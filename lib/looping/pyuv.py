#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the authors. See the file "AUTHORS" for a complete
# list.

# This file was taken from the Rose project.
# See: https://github.com/saghul/rose

from __future__ import absolute_import, print_function

import collections
import errno
import logging
import pyuv
import socket
import sys

try:
    import signal
except ImportError:
    signal = None

from . import events, winsocketpair


class PyUVEventLoop(events.AbstractEventLoop):
    """A PEP3156 style EventLoop for libuv using pyuv."""

    def __init__(self, loop=None):
        super(PyUVEventLoop, self).__init__()
        if loop is None:
            loop = pyuv.Loop.default_loop()
        self._loop = loop
        self._stop = False
        self._last_exc = None

        self._fd_map = {}
        self._signal_handlers = {}
        self._ready = collections.deque()
        self._timers = collections.deque()

        self._waker = pyuv.Async(self._loop, lambda h: None)
        self._waker.unref()

        self._ready_processor = pyuv.Check(self._loop)
        self._ready_processor.start(self._process_ready)

    def _socketpair(self):
        if hasattr(socket, 'socketpair'):
            return socket.socketpair()
        else:
            return winsocketpair.socketpair()

    def run(self):
        self._stop = False
        while not self._stop and self._run_once():
            pass

    def run_forever(self):
        handler = self.call_repeatedly(24*3600, lambda: None)
        try:
            self.run()
        finally:
            handler.cancel()

    def run_once(self, timeout=None):
        if timeout is not None:
            timer = pyuv.Timer(self._loop)
            timer.start(lambda x: None, timeout, 0)
        self._run_once()
        if timeout is not None:
            timer.close()

    def stop(self):
        self._stop = True
        self._waker.send()

    def close(self):
        self._fd_map.clear()
        self._signal_handlers.clear()
        self._ready.clear()
        self._timers.clear()

        self._waker.close()
        self._ready_processor.close()

        def cb(handle):
            if not handle.closed:
                handle.close()
        self._loop.walk(cb)
        # Run a loop iteration so that close callbacks are called and resources are freed
        assert not self._loop.run(pyuv.UV_RUN_NOWAIT)
        self._loop = None

    # Methods returning Handlers for scheduling callbacks.

    def call_later(self, delay, callback, *args):
        if delay <= 0:
            return self.call_soon(callback, *args)
        handler = events.make_handler(callback, args)
        timer = pyuv.Timer(self._loop)
        timer.handler = handler
        timer.start(self._timer_cb, delay, 0)
        self._timers.append(timer)
        return handler

    def call_repeatedly(self, interval, callback, *args):  # NEW!
        if interval <= 0:
            raise ValueError('invalid interval specified: {}'.format(interval))
        handler = events.make_handler(callback, args)
        timer = pyuv.Timer(self._loop)
        timer.handler = handler
        timer.start(self._timer_cb, interval, interval)
        self._timers.append(timer)
        return handler

    def call_soon(self, callback, *args):
        handler = events.make_handler(callback, args)
        self._ready.append(handler)
        return handler

    def call_soon_threadsafe(self, callback, *args):
        handler = self.call_soon(callback, *args)
        self._waker.send()
        return handler

    # Level-trigered I/O methods.
    # The add_*() methods return a Handler.
    # The remove_*() methods return True if something was removed,
    # False if there was nothing to delete.

    def add_reader(self, fd, callback, *args):
        handler = events.make_handler(callback, args)
        try:
            poll_h = self._fd_map[fd]
        except KeyError:
            poll_h = self._create_poll_handle(fd)
            self._fd_map[fd] = poll_h
        else:
            poll_h.stop()

        poll_h.pevents |= pyuv.UV_READABLE
        poll_h.read_handler = handler
        poll_h.start(poll_h.pevents, self._poll_cb)

        return handler

    def remove_reader(self, fd):
        try:
            poll_h = self._fd_map[fd]
        except KeyError:
            return False
        else:
            poll_h.stop()
            poll_h.pevents &= ~pyuv.UV_READABLE
            poll_h.read_handler = None
            if poll_h.pevents == 0:
                del self._fd_map[fd]
                poll_h.close()
            else:
                poll_h.start(poll_h.pevents, self._poll_cb)
            return True

    def add_writer(self, fd, callback, *args):
        handler = events.make_handler(callback, args)
        try:
            poll_h = self._fd_map[fd]
        except KeyError:
            poll_h = self._create_poll_handle(fd)
            self._fd_map[fd] = poll_h
        else:
            poll_h.stop()

        poll_h.pevents |= pyuv.UV_WRITABLE
        poll_h.write_handler = handler
        poll_h.start(poll_h.pevents, self._poll_cb)

        return handler

    def remove_writer(self, fd):
        try:
            poll_h = self._fd_map[fd]
        except KeyError:
            return False
        else:
            poll_h.stop()
            poll_h.pevents &= ~pyuv.UV_WRITABLE
            poll_h.write_handler = None
            if poll_h.pevents == 0:
                del self._fd_map[fd]
                poll_h.close()
            else:
                poll_h.start(poll_h.pevents, self._poll_cb)
            return True

    # Signal handling.

    def add_signal_handler(self, sig, callback, *args):
        self._validate_signal(sig)
        signal_h = pyuv.Signal(self._loop)
        handler = events.make_handler(callback, args)
        signal_h.handler = handler
        try:
            signal_h.start(self._signal_cb, sig)
        except Exception as e:
            signal_h.close()
            raise RuntimeError(str(e))
        else:
            self._signal_handlers[sig] = signal_h
        return handler

    def remove_signal_handler(self, sig):
        self._validate_signal(sig)
        try:
            signal_h = self._signal_handlers.pop(sig)
        except KeyError:
            return False
        del signal_h.handler
        signal_h.close()
        return True

    # Private / internal methods

    def _run_once(self):
        # Check if there are cancelled timers, if so close the handles
        for timer in [timer for timer in self._timers if timer.handler.cancelled]:
            timer.close()
            self._timers.remove(timer)
            del timer.handler

        # If there is something ready to be run, prevent the loop from blocking for i/o
        if self._ready:
            self._ready_processor.ref()
            mode = pyuv.UV_RUN_NOWAIT
        else:
            self._ready_processor.unref()
            mode = pyuv.UV_RUN_ONCE

        r = self._loop.run(mode)
        if self._last_exc is not None:
            exc, self._last_exc = self._last_exc, None
            raise exc[1]
        return r

    def _timer_cb(self, timer):
        if timer.handler.cancelled:
            del timer.handler
            self._timers.remove(timer)
            timer.close()
            return
        self._ready.append(timer.handler)
        if not timer.repeat:
            del timer.handler
            self._timers.remove(timer)
            timer.close()

    def _signal_cb(self, signal_h, signum):
        if signal_h.handler.cancelled:
            self.remove_signal_handler(signum)
            return
        self._ready.append(signal_h.handler)

    def _poll_cb(self, poll_h, events, error):
        fd = poll_h.fileno()
        if error is not None:
            # An error happened, signal both readability and writability and
            # let the error propagate
            if poll_h.read_handler is not None:
                if poll_h.read_handler.cancelled:
                    self.remove_reader(fd)
                else:
                    self._ready.append(poll_h.read_handler)
            if poll_h.write_handler is not None:
                if poll_h.write_handler.cancelled:
                    self.remove_writer(fd)
                else:
                    self._ready.append(poll_h.write_handler)
            return

        old_events = poll_h.pevents
        modified = False

        if events & pyuv.UV_READABLE:
            if poll_h.read_handler is not None:
                if poll_h.read_handler.cancelled:
                    self.remove_reader(fd)
                    modified = True
                else:
                    self._ready.append(poll_h.read_handler)
            else:
                poll_h.pevents &= ~pyuv.UV_READABLE
        if events & pyuv.UV_WRITABLE:
            if poll_h.write_handler is not None:
                if poll_h.write_handler.cancelled:
                    self.remove_writer(fd)
                    modified = True
                else:
                    self._ready.append(poll_h.write_handler)
            else:
                poll_h.pevents &= ~pyuv.UV_WRITABLE

        if not modified and old_events != poll_h.pevents:
            # Rearm the handle
            poll_h.stop()
            poll_h.start(poll_h.pevents, self._poll_cb)

    def _process_ready(self, handle):
        # This is the only place where callbacks are actually *called*.
        # All other places just add them to ready.
        # Note: We run all currently scheduled callbacks, but not any
        # callbacks scheduled by callbacks run this time around --
        # they will be run the next time (after another I/O poll).
        # Use an idiom that is threadsafe without using locks.
        ntodo = len(self._ready)
        for i in range(ntodo):
            handler = self._ready.popleft()
            if not handler.cancelled:
                try:
                    handler.callback(*handler.args)
                except Exception:
                    logging.exception('Exception in callback %s %r', handler.callback, handler.args)
                except BaseException:
                    self._last_exc = sys.exc_info()
                    break
        if not self._ready:
            self._ready_processor.unref()
        else:
            self._ready_processor.ref()

    def _create_poll_handle(self, fdobj):
        poll_h = pyuv.Poll(self._loop, self._fileobj_to_fd(fdobj))
        poll_h.pevents = 0
        poll_h.read_handler = None
        poll_h.write_handler = None
        return poll_h

    def _fileobj_to_fd(self, fileobj):
        """Return a file descriptor from a file object.

        Parameters:
        fileobj -- file descriptor, or any object with a `fileno()` method

        Returns:
        corresponding file descriptor
        """
        if isinstance(fileobj, int):
            fd = fileobj
        else:
            try:
                fd = int(fileobj.fileno())
            except (ValueError, TypeError):
                raise ValueError("Invalid file object: {!r}".format(fileobj))
        return fd

    def _validate_signal(self, sig):
        """Internal helper to validate a signal.

        Raise ValueError if the signal number is invalid or uncatchable.
        Raise RuntimeError if there is a problem setting up the handler.
        """
        if not isinstance(sig, int):
            raise TypeError('sig must be an int, not {!r}'.format(sig))
        if signal is None:
            raise RuntimeError('Signals are not supported')
        if not (1 <= sig < signal.NSIG):
            raise ValueError('sig {} out of range(1, {})'.format(sig, signal.NSIG))
        if sys.platform == 'win32':
            raise RuntimeError('Signals are not really supported on Windows')
