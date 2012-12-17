#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012 the authors. See the file "AUTHORS" for a complete list.


from setuptools import setup

version_info = {
    'name': 'looping',
    'version': '0.1',
    'description': 'An EventLoop interface for various event loops',
    'author': 'Geert Jansen',
    'author_email': 'geertj@gmail.com',
    'url': 'https://github.com/geertj/looping',
    'license': 'Apache 2.0',
    'classifiers': [
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.2'
        'Programming Language :: Python :: 3.3'
    ]
}
 
setup(
    package_dir = { '': 'lib' },
    packages = [ 'looping' ],
    install_requires = ['setuptools'],
    **version_info
)
