#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the authors. See the file "AUTHORS" for a complete
# list.

# This file was taken from the Tulip project.
# See: https://code.google.com/p/tulip

"""Tests for events.py."""

from __future__ import absolute_import, print_function

import gc
import os
import io
import select
import signal
import sys
import threading
import time
import unittest

from looping import events, pyuv


class EventLoopTestsMixin(object):

    def setUp(self):
        self.event_loop = self.create_event_loop()
        events.set_event_loop(self.event_loop)

    def tearDown(self):
        self.event_loop.close()
        gc.collect()

    def test_run(self):
        el = events.get_event_loop()
        el.run()  # Returns immediately.

    def test_call_later(self):
        el = events.get_event_loop()
        results = []
        def callback(arg):
            results.append(arg)
        el.call_later(0.1, callback, 'hello world')
        t0 = time.time()
        el.run()
        t1 = time.time()
        self.assertEqual(results, ['hello world'])
        self.assertTrue(t1-t0 >= 0.09)

    def test_call_repeatedly(self):
        el = events.get_event_loop()
        results = []
        def callback(arg):
            results.append(arg)
        el.call_repeatedly(0.03, callback, 'ho')
        el.call_later(0.1, el.stop)
        el.run()
        self.assertEqual(results, ['ho', 'ho', 'ho'])

    def test_call_soon(self):
        el = events.get_event_loop()
        results = []
        def callback(arg1, arg2):
            results.append((arg1, arg2))
        el.call_soon(callback, 'hello', 'world')
        el.run()
        self.assertEqual(results, [('hello', 'world')])

    def test_call_soon_with_handler(self):
        el = events.get_event_loop()
        results = []
        def callback():
            results.append('yeah')
        handler = events.Handler(None, callback, ())
        self.assertEqual(el.call_soon(handler), handler)
        el.run()
        self.assertEqual(results, ['yeah'])

    def test_call_soon_threadsafe(self):
        el = events.get_event_loop()
        results = []
        def callback(arg):
            results.append(arg)
        def run():
            el.call_soon_threadsafe(callback, 'hello')
        t = threading.Thread(target=run)
        el.call_later(0.1, callback, 'world')
        t0 = time.time()
        t.start()
        el.run()
        t1 = time.time()
        t.join()
        self.assertEqual(results, ['hello', 'world'])
        self.assertTrue(t1-t0 >= 0.09)

    def test_call_soon_threadsafe_with_handler(self):
        el = events.get_event_loop()
        results = []
        def callback(arg):
            results.append(arg)
        handler = events.Handler(None, callback, ('hello',))
        def run():
            self.assertEqual(el.call_soon_threadsafe(handler), handler)
        t = threading.Thread(target=run)
        el.call_later(0.1, callback, 'world')
        t0 = time.time()
        t.start()
        el.run()
        t1 = time.time()
        t.join()
        self.assertEqual(results, ['hello', 'world'])
        self.assertTrue(t1-t0 >= 0.09)

    def test_reader_callback(self):
        el = events.get_event_loop()
        r, w = el._socketpair()
        bytes_read = []
        def reader():
            try:
                data = r.recv(1024)
            except io.BlockingIOError:
                # Spurious readiness notifications are possible
                # at least on Linux -- see man select.
                return
            if data:
                bytes_read.append(data)
            else:
                self.assertTrue(el.remove_reader(r.fileno()))
                r.close()
        el.add_reader(r.fileno(), reader)
        el.call_later(0.05, w.send, b'abc')
        el.call_later(0.1, w.send, b'def')
        el.call_later(0.15, w.close)
        el.run()
        self.assertEqual(b''.join(bytes_read), b'abcdef')

    def test_reader_callback_with_handler(self):
        el = events.get_event_loop()
        r, w = el._socketpair()
        bytes_read = []
        def reader():
            try:
                data = r.recv(1024)
            except io.BlockingIOError:
                # Spurious readiness notifications are possible
                # at least on Linux -- see man select.
                return
            if data:
                bytes_read.append(data)
            else:
                self.assertTrue(el.remove_reader(r.fileno()))
                r.close()
        handler = events.Handler(None, reader, ())
        self.assertEqual(el.add_reader(r.fileno(), handler), handler)
        el.call_later(0.05, w.send, b'abc')
        el.call_later(0.1, w.send, b'def')
        el.call_later(0.15, w.close)
        el.run()
        self.assertEqual(b''.join(bytes_read), b'abcdef')

    def test_reader_callback_cancel(self):
        el = events.get_event_loop()
        r, w = el._socketpair()
        bytes_read = []
        def reader():
            try:
                data = r.recv(1024)
            except io.BlockingIOError:
                return
            if data:
                bytes_read.append(data)
            if sum(len(b) for b in bytes_read) >= 6:
                handler.cancel()
            if not data:
                r.close()
        handler = el.add_reader(r.fileno(), reader)
        el.call_later(0.05, w.send, b'abc')
        el.call_later(0.1, w.send, b'def')
        el.call_later(0.15, w.close)
        el.run()
        self.assertEqual(b''.join(bytes_read), b'abcdef')

    def test_writer_callback(self):
        el = events.get_event_loop()
        r, w = el._socketpair()
        w.setblocking(False)
        el.add_writer(w.fileno(), w.send, b'x'*(256*1024))
        def remove_writer():
            self.assertTrue(el.remove_writer(w.fileno()))
        el.call_later(0.1, remove_writer)
        el.run()
        w.close()
        data = r.recv(256*1024)
        r.close()
        self.assertTrue(len(data) >= 200)

    def test_writer_callback_with_handler(self):
        el = events.get_event_loop()
        r, w = el._socketpair()
        w.setblocking(False)
        handler = events.Handler(None, w.send, (b'x'*(256*1024),))
        self.assertEqual(el.add_writer(w.fileno(), handler), handler)
        def remove_writer():
            self.assertTrue(el.remove_writer(w.fileno()))
        el.call_later(0.1, remove_writer)
        el.run()
        w.close()
        data = r.recv(256*1024)
        r.close()
        self.assertTrue(len(data) >= 200)

    def test_writer_callback_cancel(self):
        el = events.get_event_loop()
        r, w = el._socketpair()
        w.setblocking(False)
        def sender():
            w.send(b'x'*256)
            handler.cancel()
        handler = el.add_writer(w.fileno(), sender)
        el.run()
        w.close()
        data = r.recv(1024)
        r.close()
        self.assertTrue(data == b'x'*256)

    @unittest.skipUnless(hasattr(signal, 'SIGKILL'), 'No SIGKILL')
    def test_add_signal_handler(self):
        caught = [0]
        def my_handler():
            caught[0] += 1
        el = events.get_event_loop()
        # Check error behavior first.
        self.assertRaises(TypeError, el.add_signal_handler, 'boom', my_handler)
        self.assertRaises(TypeError, el.remove_signal_handler, 'boom')
        self.assertRaises(ValueError, el.add_signal_handler, signal.NSIG+1,
                          my_handler)
        self.assertRaises(ValueError, el.remove_signal_handler, signal.NSIG+1)
        self.assertRaises(ValueError, el.add_signal_handler, 0, my_handler)
        self.assertRaises(ValueError, el.remove_signal_handler, 0)
        self.assertRaises(ValueError, el.add_signal_handler, -1, my_handler)
        self.assertRaises(ValueError, el.remove_signal_handler, -1)
        self.assertRaises(RuntimeError, el.add_signal_handler, signal.SIGKILL,
                          my_handler)
        # Removing SIGKILL doesn't raise, since we don't call signal().
        self.assertFalse(el.remove_signal_handler(signal.SIGKILL))
        # Now set a handler and handle it.
        el.add_signal_handler(signal.SIGINT, my_handler)
        el.run_once()
        os.kill(os.getpid(), signal.SIGINT)
        el.run_once()
        self.assertEqual(caught[0], 1)
        # Removing it should restore the default handler.
        self.assertTrue(el.remove_signal_handler(signal.SIGINT))
        self.assertEqual(signal.getsignal(signal.SIGINT),
                         signal.default_int_handler)
        # Removing again returns False.
        self.assertFalse(el.remove_signal_handler(signal.SIGINT))

    @unittest.skipIf(sys.platform == 'win32', 'Unix only')
    def test_cancel_signal_handler(self):
        # Cancelling the handler should remove it (eventually).
        caught = [0]
        def my_handler():
            caught[0] += 1
        el = events.get_event_loop()
        handler = el.add_signal_handler(signal.SIGINT, my_handler)
        handler.cancel()
        os.kill(os.getpid(), signal.SIGINT)
        el.run_once()
        self.assertEqual(caught[0], 0)

    @unittest.skipUnless(hasattr(signal, 'SIGALRM'), 'No SIGALRM')
    def test_signal_handling_while_selecting(self):
        # Test with a signal actually arriving during a select() call.
        caught = [0]
        def my_handler():
            caught[0] += 1
        el = events.get_event_loop()
        handler = el.add_signal_handler(signal.SIGALRM, my_handler)
        signal.setitimer(signal.ITIMER_REAL, 0.1, 0)  # Send SIGALRM once.
        el.call_later(0.15, el.stop)
        el.run_forever()
        self.assertEqual(caught[0], 1)


class PyUVEventLoopTests(EventLoopTestsMixin, unittest.TestCase):

    def create_event_loop(self):
        return pyuv.PyUVEventLoop()


class HandlerTests(unittest.TestCase):

    def test_handler(self):
        pass

    def test_make_handler(self):
        def callback(*args):
            return args
        h1 = events.Handler(None, callback, ())
        h2 = events.make_handler(None, h1, ())
        self.assertEqual(h1, h2)


class PolicyTests(unittest.TestCase):

    def test_policy(self):
        pass


if __name__ == '__main__':
    unittest.main()
