#
# This file is part of looping. Looping is free software available under the
# terms of the Apache 2.0 license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the authors. See the file "AUTHORS" for a complete
# list.


from setuptools import setup

version_info = {
    'name': 'looping',
    'version': '0.3.dev',
    'description': 'A PEP3156 interface for various event loops',
    'author': 'Geert Jansen',
    'author_email': 'geertj@gmail.com',
    'url': 'https://github.com/geertj/looping',
    'license': 'Apache 2.0',
    'classifiers': [
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.2',
        'Programming Language :: Python :: 3.3'
    ]
}
 
if __name__ == '__main__':
    setup(
        package_dir = {'': 'lib'},
        packages = ['looping', 'looping.test'],
        install_requires = ['setuptools', 'pyuv>=0.9.6'],
        test_suite = 'nose.collector',
        **version_info
    )
