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

import errno
import gc
import os
import io
import select
import signal
import socket
try:
    import ssl
except ImportError:
    ssl = None
import sys
import threading
import time
import unittest
try:
    from unittest import mock
except ImportError:
    import mock

import looping
from looping import events, util
from looping.test import test_utils


class EventLoopTestsMixin(object):

    def setUp(self):
        super(EventLoopTestsMixin, self).setUp()
        self.event_loop = self.create_event_loop()
        events.set_event_loop(self.event_loop)

    def tearDown(self):
        self.event_loop.close()
        gc.collect()
        super(EventLoopTestsMixin, self).tearDown()

    def test_run(self):
        self.event_loop.run()  # Returns immediately.

    def test_call_later(self):
        results = []
        def callback(arg):
            results.append(arg)
        self.event_loop.call_later(0.1, callback, 'hello world')
        t0 = time.time()
        self.event_loop.run()
        t1 = time.time()
        self.assertEqual(results, ['hello world'])
        self.assertTrue(t1-t0 >= 0.08)

    def test_call_repeatedly(self):
        results = []
        def callback(arg):
            results.append(arg)
        self.event_loop.call_repeatedly(0.03, callback, 'ho')
        self.event_loop.call_later(0.1, self.event_loop.stop)
        self.event_loop.run()
        self.assertEqual(results, ['ho', 'ho', 'ho'])

    def test_call_soon(self):
        results = []
        def callback(arg1, arg2):
            results.append((arg1, arg2))
        self.event_loop.call_soon(callback, 'hello', 'world')
        self.event_loop.run()
        self.assertEqual(results, [('hello', 'world')])

    def test_call_soon_with_handler(self):
        results = []
        def callback():
            results.append('yeah')
        handler = events.Handler(callback, ())
        self.assertIs(self.event_loop.call_soon(handler), handler)
        self.event_loop.run()
        self.assertEqual(results, ['yeah'])

    def test_call_soon_threadsafe(self):
        results = []
        def callback(arg):
            results.append(arg)
        def run():
            self.event_loop.call_soon_threadsafe(callback, 'hello')
        t = threading.Thread(target=run)
        self.event_loop.call_later(0.1, callback, 'world')
        t0 = time.time()
        t.start()
        self.event_loop.run()
        t1 = time.time()
        t.join()
        self.assertEqual(results, ['hello', 'world'])
        self.assertTrue(t1-t0 >= 0.08)

    def test_call_soon_threadsafe_same_thread(self):
        results = []
        def callback(arg):
            results.append(arg)
        self.event_loop.call_later(0.1, callback, 'world')
        self.event_loop.call_soon_threadsafe(callback, 'hello')
        self.event_loop.run()
        self.assertEqual(results, ['hello', 'world'])

    def test_call_soon_threadsafe_with_handler(self):
        results = []
        def callback(arg):
            results.append(arg)

        handler = events.Handler(callback, ('hello',))
        def run():
            self.assertIs(self.event_loop.call_soon_threadsafe(handler),handler)

        t = threading.Thread(target=run)
        self.event_loop.call_later(0.1, callback, 'world')

        t0 = time.time()
        t.start()
        self.event_loop.run()
        t1 = time.time()
        t.join()
        self.assertEqual(results, ['hello', 'world'])
        self.assertTrue(t1-t0 >= 0.08)

    def test_reader_callback(self):
        r, w = self.event_loop._socketpair()
        bytes_read = []
        def reader():
            try:
                data = r.recv(1024)
            except io.BlockingIOError:
                # Spurious readiness notifications are possible
                # at least on Linux -- see man select.
                return
            except socket.error as e:
                # Python 2.x
                if e.errno in util.TRYAGAIN:
                    return
                raise
            if data:
                bytes_read.append(data)
            else:
                self.assertTrue(self.event_loop.remove_reader(r.fileno()))
                r.close()
        self.event_loop.add_reader(r.fileno(), reader)
        self.event_loop.call_later(0.05, w.send, b'abc')
        self.event_loop.call_later(0.1, w.send, b'def')
        self.event_loop.call_later(0.15, w.close)
        self.event_loop.run()
        self.assertEqual(b''.join(bytes_read), b'abcdef')

    def test_reader_callback_with_handler(self):
        r, w = self.event_loop._socketpair()
        bytes_read = []
        def reader():
            try:
                data = r.recv(1024)
            except io.BlockingIOError:
                # Spurious readiness notifications are possible
                # at least on Linux -- see man select.
                return
            except socket.error as e:
                if e.errno in util.TRYAGAIN:
                    return
                raise
            if data:
                bytes_read.append(data)
            else:
                self.assertTrue(self.event_loop.remove_reader(r.fileno()))
                r.close()

        handler = events.Handler(reader, ())
        self.assertIs(handler, self.event_loop.add_reader(r.fileno(), handler))

        self.event_loop.call_later(0.05, w.send, b'abc')
        self.event_loop.call_later(0.1, w.send, b'def')
        self.event_loop.call_later(0.15, w.close)
        self.event_loop.run()
        self.assertEqual(b''.join(bytes_read), b'abcdef')

    def test_reader_callback_cancel(self):
        r, w = self.event_loop._socketpair()
        bytes_read = []
        def reader():
            try:
                data = r.recv(1024)
            except io.BlockingIOError:
                return
            except socket.error as e:
                if e.errno in util.TRYAGAIN:
                    return
                raise
            if data:
                bytes_read.append(data)
            if sum(len(b) for b in bytes_read) >= 6:
                handler.cancel()
            if not data:
                r.close()
        handler = self.event_loop.add_reader(r.fileno(), reader)
        self.event_loop.call_later(0.05, w.send, b'abc')
        self.event_loop.call_later(0.1, w.send, b'def')
        self.event_loop.call_later(0.15, w.close)
        self.event_loop.run()
        self.assertEqual(b''.join(bytes_read), b'abcdef')

    def test_writer_callback(self):
        r, w = self.event_loop._socketpair()
        w.setblocking(False)
        self.event_loop.add_writer(w.fileno(), w.send, b'x'*(256*1024))
        def remove_writer():
            self.assertTrue(self.event_loop.remove_writer(w.fileno()))
        self.event_loop.call_later(0.1, remove_writer)
        self.event_loop.run()
        w.close()
        data = r.recv(256*1024)
        r.close()
        self.assertTrue(len(data) >= 200)

    def test_writer_callback_with_handler(self):
        r, w = self.event_loop._socketpair()
        w.setblocking(False)
        handler = events.Handler(w.send, (b'x'*(256*1024),))
        self.assertIs(self.event_loop.add_writer(w.fileno(), handler), handler)
        def remove_writer():
            self.assertTrue(self.event_loop.remove_writer(w.fileno()))
        self.event_loop.call_later(0.1, remove_writer)
        self.event_loop.run()
        w.close()
        data = r.recv(256*1024)
        r.close()
        self.assertTrue(len(data) >= 200)

    def test_writer_callback_cancel(self):
        r, w = self.event_loop._socketpair()
        w.setblocking(False)
        def sender():
            w.send(b'x'*256)
            handler.cancel()
        handler = self.event_loop.add_writer(w.fileno(), sender)
        self.event_loop.run()
        w.close()
        data = r.recv(1024)
        r.close()
        self.assertTrue(data == b'x'*256)

    @unittest.skipUnless(hasattr(signal, 'SIGKILL'), 'No SIGKILL')
    def test_add_signal_handler(self):
        caught = [0]
        def my_handler():
            caught[0] += 1

        # Check error behavior first.
        self.assertRaises(
            TypeError, self.event_loop.add_signal_handler, 'boom', my_handler)
        self.assertRaises(
            TypeError, self.event_loop.remove_signal_handler, 'boom')
        self.assertRaises(
            ValueError, self.event_loop.add_signal_handler, signal.NSIG+1,
            my_handler)
        self.assertRaises(
            ValueError, self.event_loop.remove_signal_handler, signal.NSIG+1)
        self.assertRaises(
            ValueError, self.event_loop.add_signal_handler, 0, my_handler)
        self.assertRaises(
            ValueError, self.event_loop.remove_signal_handler, 0)
        self.assertRaises(
            ValueError, self.event_loop.add_signal_handler, -1, my_handler)
        self.assertRaises(
            ValueError, self.event_loop.remove_signal_handler, -1)
        self.assertRaises(
            RuntimeError, self.event_loop.add_signal_handler, signal.SIGKILL,
            my_handler)
        # Removing SIGKILL doesn't raise, since we don't call signal().
        self.assertFalse(self.event_loop.remove_signal_handler(signal.SIGKILL))
        # Now set a handler and handle it.
        self.event_loop.add_signal_handler(signal.SIGINT, my_handler)
        self.event_loop.run_once()
        os.kill(os.getpid(), signal.SIGINT)
        self.event_loop.run_once()
        self.assertEqual(caught[0], 1)
        # Removing it should restore the default handler.
        self.assertTrue(self.event_loop.remove_signal_handler(signal.SIGINT))
        self.assertEqual(signal.getsignal(signal.SIGINT),
                         signal.default_int_handler)
        # Removing again returns False.
        self.assertFalse(self.event_loop.remove_signal_handler(signal.SIGINT))

    @unittest.skipIf(sys.platform == 'win32', 'Unix only')
    def test_cancel_signal_handler(self):
        # Cancelling the handler should remove it (eventually).
        caught = [0]
        def my_handler():
            caught[0] += 1

        handler = self.event_loop.add_signal_handler(signal.SIGINT, my_handler)
        handler.cancel()
        os.kill(os.getpid(), signal.SIGINT)
        self.event_loop.run_once()
        self.assertEqual(caught[0], 0)

    @unittest.skipUnless(hasattr(signal, 'SIGALRM'), 'No SIGALRM')
    def test_signal_handling_while_selecting(self):
        # Test with a signal actually arriving during a select() call.
        caught = [0]
        def my_handler():
            caught[0] += 1

        handler = self.event_loop.add_signal_handler(signal.SIGALRM, my_handler)
        signal.setitimer(signal.ITIMER_REAL, 0.1, 0)  # Send SIGALRM once.
        self.event_loop.call_later(0.15, self.event_loop.stop)
        self.event_loop.run_forever()
        self.assertEqual(caught[0], 1)


if hasattr(looping, 'PyUVEventLoop'):
    class PyUVEventLoopTests(EventLoopTestsMixin,
                             test_utils.LogTrackingTestCase):
        def create_event_loop(self):
            return looping.PyUVEventLoop()

if hasattr(looping, 'PySideEventLoop'):
    class PySideEventLoopTests(EventLoopTestsMixin,
                               test_utils.LogTrackingTestCase):
        def create_event_loop(self):
            return looping.PySideEventLoop()

        def test_add_signal_handler(self):
            pass

        def test_cancel_signal_handler(self):
            pass

        def test_signal_handling_while_selecting(self):
            pass


class HandlerTests(unittest.TestCase):

    def test_handler(self):
        def callback(*args):
            return args

        args = ()
        h = events.Handler(callback, args)
        self.assertIs(h.callback, callback)
        self.assertIs(h.args, args)
        self.assertFalse(h.cancelled)

        r = repr(h)
        self.assertTrue(r.startswith('Handler(<function'))
        self.assertTrue(r.endswith('())'))

        h.cancel()
        self.assertTrue(h.cancelled)

        r = repr(h)
        self.assertTrue(r.startswith('Handler(<function'))
        self.assertTrue(r.endswith('())<cancelled>'))

    def test_make_handler(self):
        def callback(*args):
            return args
        h1 = events.Handler(callback, ())
        h2 = events.make_handler(h1, ())
        self.assertIs(h1, h2)

        self.assertRaises(AssertionError,
                          events.make_handler, h1, (1,2,))


class TimerTests(unittest.TestCase):

    def test_timer(self):
        def callback(*args):
            return args

        args = ()
        when = time.time()
        h = events.Timer(when, callback, args)
        self.assertIs(h.callback, callback)
        self.assertIs(h.args, args)
        self.assertFalse(h.cancelled)

        r = repr(h)
        self.assertTrue(r.endswith('())'))

        h.cancel()
        self.assertTrue(h.cancelled)

        r = repr(h)
        self.assertTrue(r.endswith('())<cancelled>'))

        self.assertRaises(AssertionError, events.Timer, None, callback, args)

    def test_timer_comparison(self):
        def callback(*args):
            return args

        when = time.time()

        h1 = events.Timer(when, callback, ())
        h2 = events.Timer(when, callback, ())
        self.assertFalse(h1 < h2)
        self.assertFalse(h2 < h1)
        self.assertTrue(h1 <= h2)
        self.assertTrue(h2 <= h1)
        self.assertFalse(h1 > h2)
        self.assertFalse(h2 > h1)
        self.assertTrue(h1 >= h2)
        self.assertTrue(h2 >= h1)
        self.assertTrue(h1 == h2)
        self.assertFalse(h1 != h2)

        h2.cancel()
        self.assertFalse(h1 == h2)

        h1 = events.Timer(when, callback, ())
        h2 = events.Timer(when + 10.0, callback, ())
        self.assertTrue(h1 < h2)
        self.assertFalse(h2 < h1)
        self.assertTrue(h1 <= h2)
        self.assertFalse(h2 <= h1)
        self.assertFalse(h1 > h2)
        self.assertTrue(h2 > h1)
        self.assertFalse(h1 >= h2)
        self.assertTrue(h2 >= h1)
        self.assertFalse(h1 == h2)
        self.assertTrue(h1 != h2)

        h3 = events.Handler(callback, ())
        self.assertIs(NotImplemented, h1.__eq__(h3))
        self.assertIs(NotImplemented, h1.__ne__(h3))


class AbstractEventLoopTests(unittest.TestCase):

    def test_not_imlemented(self):
        f = mock.Mock()
        ev_loop = events.AbstractEventLoop()
        self.assertRaises(
            NotImplementedError, ev_loop.run)
        self.assertRaises(
            NotImplementedError, ev_loop.run_forever)
        self.assertRaises(
            NotImplementedError, ev_loop.run_once)
        self.assertRaises(
            NotImplementedError, ev_loop.run_until_complete, None)
        self.assertRaises(
            NotImplementedError, ev_loop.stop)
        self.assertRaises(
            NotImplementedError, ev_loop.call_later, None, None)
        self.assertRaises(
            NotImplementedError, ev_loop.call_repeatedly, None, None)
        self.assertRaises(
            NotImplementedError, ev_loop.call_soon, None)
        self.assertRaises(
            NotImplementedError, ev_loop.call_soon_threadsafe, None)
        self.assertRaises(
            NotImplementedError, ev_loop.wrap_future, f)
        self.assertRaises(
            NotImplementedError, ev_loop.run_in_executor, f, f)
        self.assertRaises(
            NotImplementedError, ev_loop.getaddrinfo, 'localhost', 8080)
        self.assertRaises(
            NotImplementedError, ev_loop.getnameinfo, ('localhost', 8080))
        self.assertRaises(
            NotImplementedError, ev_loop.create_connection, f)
        self.assertRaises(
            NotImplementedError, ev_loop.start_serving, f)
        self.assertRaises(
            NotImplementedError, ev_loop.add_reader, 1, f)
        self.assertRaises(
            NotImplementedError, ev_loop.remove_reader, 1)
        self.assertRaises(
            NotImplementedError, ev_loop.add_writer, 1, f)
        self.assertRaises(
            NotImplementedError, ev_loop.remove_writer, 1)
        self.assertRaises(
            NotImplementedError, ev_loop.sock_recv, f, 10)
        self.assertRaises(
            NotImplementedError, ev_loop.sock_sendall, f, 10)
        self.assertRaises(
            NotImplementedError, ev_loop.sock_connect, f, f)
        self.assertRaises(
            NotImplementedError, ev_loop.sock_accept, f)
        self.assertRaises(
            NotImplementedError, ev_loop.add_signal_handler, 1, f)
        self.assertRaises(
            NotImplementedError, ev_loop.remove_signal_handler, 1)


class PolicyTests(unittest.TestCase):

    def test_event_loop_policy(self):
        policy = events.EventLoopPolicy()
        self.assertRaises(NotImplementedError, policy.get_event_loop)
        self.assertRaises(NotImplementedError, policy.set_event_loop, object())
        self.assertRaises(NotImplementedError, policy.new_event_loop)

    def test_get_event_loop(self):
        policy = events.DefaultEventLoopPolicy()
        self.assertIsNone(policy._event_loop)

        event_loop = policy.get_event_loop()
        self.assertIsInstance(event_loop, events.AbstractEventLoop)

        self.assertIs(policy._event_loop, event_loop)
        self.assertIs(event_loop, policy.get_event_loop())

    @mock.patch('looping.events.threading')
    def test_get_event_loop_thread(self, m_threading):
        m_t = m_threading.current_thread.return_value = mock.Mock()
        m_t.name = 'Thread 1'

        policy = events.DefaultEventLoopPolicy()
        self.assertIsNone(policy.get_event_loop())

    def test_new_event_loop(self):
        policy = events.DefaultEventLoopPolicy()

        event_loop = policy.new_event_loop()
        self.assertIsInstance(event_loop, events.AbstractEventLoop)

    def test_set_event_loop(self):
        policy = events.DefaultEventLoopPolicy()
        old_event_loop = policy.get_event_loop()

        self.assertRaises(AssertionError, policy.set_event_loop, object())

        event_loop = policy.new_event_loop()
        policy.set_event_loop(event_loop)
        self.assertIs(event_loop, policy.get_event_loop())
        self.assertIsNot(old_event_loop, policy.get_event_loop())

    def test_get_event_loop_policy(self):
        policy = events.get_event_loop_policy()
        self.assertIsInstance(policy, events.EventLoopPolicy)
        self.assertIs(policy, events.get_event_loop_policy())

    def test_set_event_loop_policy(self):
        self.assertRaises(
            AssertionError, events.set_event_loop_policy, object())

        old_policy = events.get_event_loop_policy()

        policy = events.DefaultEventLoopPolicy()
        events.set_event_loop_policy(policy)
        self.assertIs(policy, events.get_event_loop_policy())


if __name__ == '__main__':
    unittest.main()
