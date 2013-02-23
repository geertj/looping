#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the authors. See the file "AUTHORS" for a complete
# list.

from __future__ import absolute_import, print_function

import sys
import socket
import logging
import weakref
import select
import collections

from PySide.QtCore import (QObject, QSocketNotifier, QTimer,
        QCoreApplication, QEvent, QEventLoop, QThread,
        QAbstractEventDispatcher)
from . import events


class RunCallbacks(QEvent):

    EventType = QEvent.Type(QEvent.registerEventType())

    def __init__(self):
        super(RunCallbacks, self).__init__(self.EventType)


class EventProcessor(QObject):

    def __init__(self, qapp, loop):
        super(EventProcessor, self).__init__(parent=qapp)
        self._qapp = qapp
        self._loop = loop  # a reference to ensure the loop is kept alive
        self._queue = collections.deque()
        dispatcher = QAbstractEventDispatcher.instance()
        dispatcher.awake.connect(self.run)

    def event(self, event):
        if event.type() == RunCallbacks.EventType:
            self.run()
            return True
        else:
            return False

    def run(self):
        ntodo = len(self._queue)
        for i in range(ntodo):
            handler = self._queue.popleft()
            if handler.cancelled:
                continue
            try:
                handler.callback(*handler.args)
            except Exception as e:
                logging.exception('Exception in callback %s %r',
                                  handler.callback, handler.args)

    @property
    def pending(self):
        return len(self._queue) > 0

    def submit(self, handler):
        self._queue.append(handler)

    def wakeup(self):
        event = RunCallbacks()
        self._qapp.postEvent(self, event)


class PySideEventLoop(events.AbstractEventLoop):
    """A PEP3156 style EventLoop for Qt4 using PySide."""

    def __init__(self):
        super(PySideEventLoop, self).__init__()
        qapp = QCoreApplication.instance()
        if qapp is None:
            qapp = QCoreApplication(sys.argv)
        self._qapp = qapp
        self._stop = False
        self._timers = set()
        self._readers = {}
        self._writers = {}
        self._processor = EventProcessor(qapp, self)

    # Run methods

    def run_once(self, timeout=None):
        events = QEventLoop.AllEvents | QEventLoop.WaitForMoreEvents
        if timeout is None:
            self._qapp.processEvents(events)
        else:
            self._qapp.processEvents(events, timeout * 1000)

    def run(self):
        """Run until there are no more events.
        This only looks at events scheduled through the event loop.
        """
        self._stop = False
        while not self._stop:
            have_sources = self._timers or self._readers or self._writers
            if not self._processor.pending and not have_sources:
                break
            events = QEventLoop.AllEvents
            if not self._processor.pending:
                events |= QEventLoop.WaitForMoreEvents
            self._qapp.processEvents(events)
            if self._processor.pending:
                self._processor.run()

    def run_forever(self):
        """Run the loop until stop() is called."""
        handler = self.call_repeatedly(24*3600, lambda: None)
        try:
            self.run()
        finally:
            handler.cancel()

    def stop(self):
        self._stop = True

    def close(self):
        for timer in self._timers:
            timer.stop()
        self._timers.clear()
        for qsn in self._readers.values():
            qsn.setEnabled(False)
        self._readers.clear()
        for qsn in self._writers.values():
            qsn.setEnabled(False)
        self._writers.clear()

    def _check_thread(self):
        if QThread.currentThread() != self._processor.thread():
            err = 'Method must be called from thread owning the loop.'
            raise RuntimeError(err)

    def _socketpair(self):
        if hasattr(socket, 'socketpair'):
            return socket.socketpair()
        else:
            return winsocketpair.socketpair()
 
    # Timers..

    def _create_timer(self, interval, single_shot, handler):
        timer = QTimer()
        timer.setInterval(1000 * interval)
        timer.setSingleShot(single_shot)
        self._timers.add(timer)
        wref = weakref.ref(timer)
        def callback():
            timer = wref()
            if single_shot and timer:
                timer.stop()
                self._timers.discard(timer)
            self._processor.submit(handler)
        timer.timeout.connect(callback)
        def cancel():
            timer = wref()
            if timer:
                timer.stop()
                self._timers.discard(timer)
        handler.cancel_callback = cancel
        timer.start()
        return timer

    def call_later(self, when, callback, *args):
        self._check_thread()
        handler = events.make_handler(callback, args)
        self._create_timer(when, True, handler)
        return handler

    def call_repeatedly(self, interval, callback, *args):
        self._check_thread()
        handler = events.make_handler(callback, args)
        self._create_timer(interval, False, handler)
        return handler

    def call_soon(self, callback, *args):
        self._check_thread()
        handler = events.make_handler(callback, args)
        self._processor.submit(handler)
        return handler

    def call_soon_threadsafe(self, callback, *args):
        handler = events.make_handler(callback, args)
        self._processor.submit(handler)
        self._processor.wakeup()
        return handler

    # File descriptor operations

    def _create_qsn(self, fd, events, handler):
        if events == QSocketNotifier.Read:
            notifiers = self._readers
        elif events == QSocketNotifier.Write:
            notifiers = self._writers
        qsn = notifiers.get(fd)
        if qsn is not None:
            qsn.setEnabled(False)
        qsn = QSocketNotifier(fd, events)
        notifiers[fd] = qsn
        qsn.activated.connect(lambda: self._processor.submit(handler))
        wref = weakref.ref(qsn)
        def cancel():
            qsn = wref()
            if qsn:
                qsn.setEnabled(False)
            if fd in notifiers and notifiers[fd] is qsn:
                del notifiers[fd]
        handler.cancel_callback = cancel 
        qsn.setEnabled(True)
        return qsn

    def add_reader(self, fd, callback, *args):
        self._check_thread()
        handler = events.make_handler(callback, args)
        self._create_qsn(fd, QSocketNotifier.Read, handler)
        return handler

    def add_writer(self, fd, callback, *args):
        self._check_thread()
        handler = events.make_handler(callback, args)
        self._create_qsn(fd, QSocketNotifier.Write, handler)
        return handler

    def remove_reader(self, fd):
        qsn = self._readers.get(fd)
        if not qsn:
            return False
        qsn.setEnabled(False)
        del self._readers[fd]
        return True

    def remove_writer(self, fd):
        qsn = self._writers.get(fd)
        if not qsn:
            return False
        qsn.setEnabled(False)
        del self._writers[fd]
        return True
