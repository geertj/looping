#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012 the authors. See the file "AUTHORS" for a complete list.

from __future__ import absolute_import, print_function

import sys
import logging
from PySide.QtCore import (QObject, QSocketNotifier, QTimer,
        QCoreApplication, QEventLoop, QAbstractEventDispatcher)
from . import events


# XXX: tests will crash if DelayedCall does not inherit from QObject.
# Probably a lifecycle issue where the callback calls into an unreferences
# object. Need to check if there isn't a more serious issue.

class Handler(QObject):

    def __init__(self, event, callback, args, kwds=None, single_shot=False):
        super(Handler, self).__init__()
        self.callback = callback
        self.args = args
        self.kwds = kwds
        self.event = event
        self.single_shot = single_shot
        self.cancelled = False

    def cancel(self):
        if hasattr(self.event, 'setEnabled'):
            self.event.setEnabled(False)
            self.event.activated.disconnect(self)
        elif hasattr(self.event, 'stop'):
            self.event.stop()
            self.event.timeout.disconnect(self)
        elif hasattr(self.event, 'aboutToBlock'):
            self.event.aboutToBlock.disconnect(self)
        self.cancelled = True

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

    def __init__(self, qapp=None):
        super(EventLoop, self).__init__()
        if qapp is None:
            qapp = QCoreApplication.instance()
            if qapp is None:
                qapp = QCoreApplication(sys.argv)
        self.qapp = qapp
        self.readers = {}
        self.writers = {}

    def add_reader(self, fd, callback, *args):
        handler = self.readers.get(fd)
        if handler:
            raise ValueError('cannot add multiple readers per fd')
        handler = Handler(None, callback, args)
        notifier = QSocketNotifier(fd, QSocketNotifier.Read)
        handler.event = notifier
        self.readers[fd] = handler
        notifier.activated.connect(handler)
        notifier.setEnabled(True)
        return handler

    def add_writer(self, fd, callback, *args):
        handler = self.writers.get(fd)
        if handlerl:
            raise ValueError('cannot add multiple writers per fd')
        handler = Handler(None, callback, args)
        notifier = QSocketNotifier(fd, QSocketNotifier.Write)
        handler.event = notifier
        self.writers[fd] = handler
        notifier.activated.connect(handler)
        notifier.setEnabled(True)
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

    def call_soon(self, repeat, callback, *args):
        handler = Handler(None, callback, args, True)
        dispatcher = QAbstractEventDispatcher.instance()
        handler.event = dispatcher
        dispatcher.aboutToBlock.connect(handler)
        return handler

    def call_later(self, when, callback, *args):
        handler = Handler(None, callback, args, True)
        timer = QTimer()
        handler.event = timer
        timer.timeout.connect(handler)
        timer.setInterval(when)
        timer.setSingleShot(True)
        timer.start()
        return handler

    def call_repeatedly(self, interval, callback, *args):
        handler = Handler(None, callback, args)
        timer = QTimer()
        handler.event = timer
        timer.timeout.connect(handler)
        timer.setInterval(interval)
        timer.setSingleShot(False)
        timer.start()
        return handler

    def call_every_iteration(self, callback, *args):
        handler = Handler(None, callback, args)
        dispatcher = QAbstractEventDispatcher.instance()
        handler.event = dispatcher
        dispatcher.aboutToBlock.connect(handler)
        return handler

    def run_once(self, timeout=None):
        events = QEventLoop.AllEvents | QEventLoop.WaitForMoreEvents
        if timeout is None:
            self.qapp.processEvents(events)
        else:
            self.qapp.processEvents(events, timeout * 1000)

    def run(self):
        self.qapp.exec_()
