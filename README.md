NSCommander
===========

Linux Network Namespace generator.
Uses yaml configuration as an input to create and destroy Linux Network Namespaces.

Features
========

* Create and destroy Namespaces
* Create and destroy Virtual Ethernet interfaces in and between Namespaces
* Manage IP-addresses and routes in namespaces
* Manage IPv6-addresses and routes in namespaces
* Jinja2 templates for external configuration files
* Start processes after namespaces are created and kill when namespaces are destroyed 


How to run
==========

    ./nscommander -c <configuration.yaml> (create|destroy|restart|dump|templates)

For example:

    ./nscommander.py -c examples/simple.yaml create
    traceroute 10.2.3.1
    traceroute to 10.2.3.1 (10.2.3.1), 30 hops max, 60 byte packets
    1  10.2.4.1 (10.2.4.1)  0.044 ms  0.009 ms  0.008 ms
    2  10.2.3.1 (10.2.3.1)  0.022 ms  0.011 ms  0.009 ms
    ./nscommander.py -c examples/simple.yaml destroy


See examples directory for more examples


License
=======
The MIT License (MIT)
Copyright (c) 2016 Antti Jaakkola

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.