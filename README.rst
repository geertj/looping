Looping
=======

This package contains ``EventLoop`` implementations for various well known
event loops. The ``EventLoop`` interface is currently being defined in PEP3156
[1]_ and the "Tulip" project [2]_.

Curently supported event loops are:

* libuv (via pyuv)
* Qt (via PySide)

This package supports Python 2.6, Python 2.7 and Python 3.2+.

The event loops only implement the callback interface, so e.g. ``add_reader()``
and friends, the ``call_soon()`` timer related functions, and the
``add_signal_handler()`` signal related functions. The other parts of the event
loop interface require ``tulip.Future`` which in turn depends on the ``yield
from`` statement. This is Python 3.3+ and is not supported in looping.

Usage
=====

The ``looping`` package defines two event loops:

* ``PyUVEventLoop``. This loop will be available if the ``pyuv`` package is
  found.
* ``PySideEventLoop``. This loop will be avaialble if the ``PySide`` package
  is found.

You can set a default loop for the current thread using ``set_event_loop()``.

License
=======

This package is licensed under the Apache 2 license (like tulip).

.. [1] http://www.python.org/dev/peps/pep-3156/
.. [2] https://code.google.com/p/tulip/
