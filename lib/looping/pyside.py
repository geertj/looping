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


# Allow this module to be compiled even if pyev is not installed
try:
    from PySide.QtCore import (QObject, QSocketNotifier, QTimer,
                               QCoreApplication, QEventLoop,
                               QAbstractEventDispatcher)
    available = True
except ImportError:
    available = False
    QObject = object


# XXX: tests will crash if DelayedCall does not inherit from QObject.
# Probably a lifecycle issue where the callback calls into an unreferences
# object. Need to check if there isn't a more serious issue.

class DelayedCall(QObject):

    def __init__(self, event, callback, args, kwds=None, repeat=True):
        super(DelayedCall, self).__init__()
        self.repeat = repeat
        self.callback = callback
        self.args = args
        self.kwds = kwds
        self.event = event

    def cancel(self):
        if hasattr(self.event, 'setEnabled'):
            self.event.setEnabled(False)
            self.event.activated.disconnect(self._callback)
        elif hasattr(self.event, 'stop'):
            self.event.stop()
            self.event.timeout.disconnect(self._callback)
        elif hasattr(self.event, 'aboutToBlock'):
            self.event.aboutToBlock.disconnect(self._callback)

    def _callback(self, *ignored):
        try:
            if self.kwds:
                self.callback(*self.args, **self.kwds)
            else:
                self.callback(*self.args)
        except Exception:
            logging.exception('Exception in callback %s %r',
                               self.callback, self.args)
        if not self.repeat:
            self.cancel()
        elif hasattr(self.event, 'setInterval'):
            self.event.setInterval(self.repeat)


class EventLoop(object):
    """An EventLoop based on libev (using pyev)."""

    def __init__(self, qapp=None):
        if not available:
            raise ImportError('PySide is not available on this system')
        super(EventLoop, self).__init__()
        if qapp is None:
            qapp = QCoreApplication.instance()
            if qapp is None:
                raise RuntimeError('No Q(Core)Application instantiated')
        self.qapp = qapp
        self.readers = {}
        self.writers = {}

    def add_reader(self, fd, callback, *args):
        dcall = self.readers.get(fd)
        if dcall:
            raise ValueError('cannot add multiple readers per fd')
        notifier = QSocketNotifier(fd, QSocketNotifier.Read)
        dcall = DelayedCall(notifier, callback, args)
        self.readers[fd] = dcall
        notifier.activated.connect(dcall._callback)
        notifier.setEnabled(True)
        return dcall

    def add_writer(self, fd, callback, *args):
        dcall = self.readers.get(fd)
        if dcall:
            raise ValueError('cannot add multiple readers per fd')
        notifier = QSocketNotifier(fd, QSocketNotifier.Write)
        dcall = DelayedCall(notifier, callback, args)
        self.writers[fd] = dcall
        notifier.activated.connect(dcall._callback)
        notifier.setEnabled(True)
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
        dispatcher = QAbstractEventDispatcher.instance()
        dcall = DelayedCall(dispatcher, callback, args, repeat)
        dispatcher.aboutToBlock.connect(dcall._callback)
        return dcall

    def call_later(self, when, repeat, callback, *args):
        if when >= 10000000:
            when -= self.loop.now()
        if when <= 0:
            raise ValueError('illegal timeout')
        timer = QTimer()
        dcall = DelayedCall(timer, callback, args, repeat)
        timer.timeout.connect(dcall._callback)
        timer.setInterval(when)
        timer.setSingleShot(True)
        timer.start()
        return dcall

    def run_once(self, timeout=None):
        events = QEventLoop.AllEvents | QEventLoop.WaitForMoreEvents
        if timeout is None:
            self.qapp.processEvents(events)
        else:
            self.qapp.processEvents(events, timeout * 1000)

    def run(self):
        self.qapp.exec_()
