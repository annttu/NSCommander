#!/usr/bin/env python3
# encoding: utf-8

"""
Linux IP tool library for Python

Currently supports:
 - creating and destroying network namespaces
 - creating, destroying and assigning veth interfaces to namespaces
 - creating routes
 - creating ECMP routes
 - adding addresses to interfaces
 - parsing YAML presentation of network to create
"""

"""
TODO:

* Generic config templating (jinja2)
* Yaml templating

"""

import subprocess
import string
import random
import sys
import yaml
import logging
import jinja2

logger = logging.getLogger("ipns")

IPCOMMAND = '/bin/ip'


class IPException(Exception):
    pass


def random_string(prefix="", length=16):
    return prefix + ''.join([random.choice(string.ascii_lowercase + string.digits) for x in range(length)])


class IPContext(object):
    def __init__(self, namespace=None):
        self.namespace = namespace

    def _ns_prefix(self):
        if not self.namespace:
            return []
        return [IPCOMMAND, 'netns', 'exec', self.namespace]

    def run(self, *args, background=False):
        command = self._ns_prefix() + list(args)
        logger.debug("Executing command: %s" % ' '.join(command))
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if background:
            return
        (stdout, stderr) = p.communicate()
        return_code = p.wait()

        if return_code != 0:
            raise IPException("%s command failed:\n%s\n%s" % (' '.join(command), stdout, stderr))
        return stdout.decode("utf-8")


class Interface(object):
    def __init__(self, context, name):
        self.name = name
        self.context = context
        self.addresses = []
        self.addresses6 = []

    def up(self):
        self.context.run(IPCOMMAND, 'link', 'set', self.name, 'up')

    def down(self):
        self.context.run(IPCOMMAND, 'link', 'set', self.name, 'down')

    def _get_addresses(self):
        self.addresses = []
        for line in self.context.run(IPCOMMAND, '-4', 'addr', 'show', 'dev', self.name).splitlines():
            line = line.strip()
            if line.startswith('inet '):
                self.addresses.append(line.split()[1].strip())

    def _get_addresses6(self):
        self.addresses6 = []
        for line in self.context.run(IPCOMMAND, '-6', 'addr', 'show', 'dev', self.name).splitlines():
            line = line.strip()
            if line.startswith('inet6 '):
                self.addresses6.append(line.split()[1].strip())

    def add_address(self, address):
        self._get_addresses()
        if address not in self.addresses:
            self.context.run(IPCOMMAND, 'address', 'add', address, 'dev', self.name)
            self.addresses.append(address)

    def delete_address(self, address):
        self._get_addresses()
        if address in self.addresses:
            self.context.run(IPCOMMAND, 'address', 'delete', address, 'dev', self.name)
            self.addresses.pop(self.addresses.index(address))

    def add_address6(self, address):
        self._get_addresses6()
        if address not in self.addresses6:
            self.context.run(IPCOMMAND, '-6', 'address', 'add', address, 'dev', self.name)
            self.addresses6.append(address)

    def delete_address6(self, address):
        self._get_addresses6()
        if address in self.addresses6:
            self.context.run(IPCOMMAND, '-6', 'address', 'delete', address, 'dev', self.name)
            self.addresses6.pop(self.addresses6.index(address))


class IP(object):
    def __init__(self, namespace=None):
        self.namespace = namespace
        self.context = IPContext(namespace=self.namespace)

    def _route(self, destination, nexthop, state="exists", ipversion='4'):
        routes = [x.split()[0] for x in self.context.run(IPCOMMAND, '-%s' % ipversion, 'route', 'list').splitlines()]
        if state == "exists":
            if destination not in routes:
                self.context.run(IPCOMMAND, 'route', 'add', destination, 'via', nexthop)
        elif state == "absent":
            if destination in routes:
                self.context.run(IPCOMMAND, 'route', 'delete', destination, 'via', nexthop)

    def route(self, destination, nexthop, state="exists"):
        return self._route(destination, nexthop, state, ipversion='4')

    def route6(self, destination, nexthop, state="exists"):
        return self._route(destination, nexthop, state, ipversion='6')

    def _ecmp_route(self, destination, nexthops, state="exists", ipversion='4'):
        routes = [x.split()[0] for x in self.context.run(IPCOMMAND, '-%s' % ipversion, 'route', 'list').splitlines()]
        if state == "exists":
            if destination not in routes:
                cmd = []
                for nexthop in nexthops:
                    cmd += ['nexthop', 'via', nexthop['via']]
                    if 'weight' in nexthop:
                        cmd += ['weight', str(nexthop['weight'])]
                    if 'interface' in nexthop:
                        cmd += ['interface', str(nexthop['interface'])]
                self.context.run(IPCOMMAND, '-%s' % ipversion, 'route', 'add', destination, *cmd)
        elif state == "absent":
            if destination in routes:
                self.context.run(IPCOMMAND, 'route', 'delete', destination)

    def ecmp_route(self, destination, nexthops, state="exists"):
        return self._ecmp_route(destination, nexthops, state=state, ipversion='4')

    def ecmp_route6(self, destination, nexthops, state="exists"):
        return self._ecmp_route(destination, nexthops, state=state, ipversion='6')

    def netns_list(self):
        return [x.strip() for x in self.context.run(IPCOMMAND, 'netns', 'list').splitlines()]

    def netns_add(self, name):
        if not name:
            raise IPException("Invalid empty namespace name")
        if name not in self.netns_list():
            self.context.run(IPCOMMAND, 'netns', 'add', name)
            self.context.run('/sbin/sysctl', '-w', 'net.ipv4.ip_forward=1')
            self.context.run('/sbin/sysctl', '-w', 'net.ipv4.conf.all.forwarding=1')
            self.context.run('/sbin/sysctl', '-w', 'net.ipv6.conf.all.forwarding=1')


    def netns_del(self, name):
        if not name:
            raise IPException("Invalid empty namespace name")
        if name in self.netns_list():
            self.context.run(IPCOMMAND, 'netns', 'delete', name)

    def netns(self, name=None):
        if self.namespace:
            raise IPException("Cannot create namespace to namespace")
        if not name:
            name = random_string(prefix="ns_", length=13)
        if name != 'global':
            self.netns_add(name)
        return NetNS(name)

    def interface(self, name):
        return Interface(self.context, name)

    def veth(self, other, my_interface, their_interface):
        """
        Create virtual ethernet interface between this and other namespace
        :param other: Another namespace where other end of veth is located
        :return: Tuple containing two interfaces
        """
        #if len(prefix) > 13:
        #    prefix = prefix[:13]
        #if not name:
        #    name = random_string(prefix, length=13 - len(prefix))
        #my_interface = '%s-a' % name
        #their_interface = '%s-b' % name
        self.context.run(IPCOMMAND, 'link', 'add', my_interface, 'type', 'veth', 'peer', 'name', their_interface)
        self.context.run(IPCOMMAND  , 'link', 'set', their_interface, 'netns', other.name)
        return self.interface(my_interface), other.ip.interface(their_interface)


class NetNS(object):
    def __init__(self, name):
        self.name = name
        if name == "global":
            nsname = None
        else:
            nsname = name
        self.ip = IP(namespace=nsname)


def expand_string(string, namespace={}):
    env = jinja2.Environment()
    env.globals.update({'namespace': namespace})
    return env.from_string(string).render()


def normalize_config(config):
    if 'namespaces' not in config:
        config['namespaces'] = []
    for name, namespace in config['namespaces'].items():
        if 'name' not in namespace:
            namespace['name'] = name
        if 'routes' not in namespace:
            namespace['routes'] = []
        if 'routes6' not in namespace:
            namespace['routes6'] = []
        if 'interfaces' not in namespace:
            namespace['interfaces'] = []
        if 'run' not in namespace:
            namespace['run'] = []
        if 'templates' not in namespace:
            namespace['templates'] = []
        for route in namespace['routes']:
            if 'destination' not in route:
                raise IPException("nexthop missing from route on namespace '%s'" % (name))
            if 'nexthop' not in route:
                raise IPException("nexthop missing from route '%s' on namespace '%s'" % (route['destination'], name))
            if type(route['nexthop']) == str:
                route['nexthop'] = [{'via': route['nexthop']}]
            for nexthop in route['nexthop']:
                if 'via' not in nexthop:
                    raise IPException("via parameter missing from route '%s' on namespace '%s'" % (route['destination'], name))
                if len(route['nexthop']) > 1:
                    if 'weight' not in nexthop:
                        nexthop['weight'] = "1"
        for route in namespace['routes6']:
            if 'destination' not in route:
                raise IPException("nexthop missing from route6 on namespace '%s'" % (name))
            if 'nexthop' not in route:
                raise IPException("nexthop missing from route6 '%s' on namespace '%s'" % (route['destination'], name))
            if type(route['nexthop']) == str:
                route['nexthop'] = [{'via': route['nexthop']}]
            for nexthop in route['nexthop']:
                if 'via' not in nexthop:
                    raise IPException("via parameter missing from route '%s' on namespace '%s'" % (route['destination'], name))
                if len(route['nexthop']) > 1:
                    if 'weight' not in nexthop:
                        nexthop['weight'] = "1"

        for interface in namespace['interfaces']:
            if 'type' not in interface:
                interface['type'] = "normal"
            if interface['type'] == 'veth':
                if 'name_prefix' not in interface:
                    interface['name_prefix'] = random_string("veth-", length=8)
                if 'my_interface' not in interface:
                    interface['my_interface'] = "%s-a" % interface['name_prefix']
                if 'their_interface' not in interface:
                    interface['their_interface'] = "%s-a" % interface['name_prefix']
            elif interface['type'] == "normal":
                pass
            else:
                raise IPException("Unknown interface type %s" % interface['type'])

        for run in namespace['run']:
            if 'command' not in run:
                raise IPException("Command missing from run in namespace '%s'" % (name,))
            if 'args' not in run:
                run['args'] = []
            args = []
            for arg in run['args']:
                print(arg)
                args.append(expand_string(arg, namespace))
            run['args'] = args
            if 'background' not in run:
                run['background'] = False
            run['background'] = bool(run['background'])

        for template in namespace['templates']:
            if 'source' not in template:
                raise IPException("source missing from tempate in namespace '%s'" % (name,))
            template['source'] = expand_string(template['source'], namespace)
            if 'destination' not in template:
                raise IPException("destination missing from tempate in namespace '%s'" % (name,))
            template['destination'] = expand_string(template['destination'], namespace)
            with open(template['source'], 'rb') as t:
                with open(template['destination'], 'wb') as o:
                    o.write(expand_string(t.read().decode("utf-8"), namespace).encode("utf-8"))
    return config


def create_from_config(config):
    namespaces = {}
    # Create all namespaces first
    for namespace in config['namespaces'].keys():
        namespaces[namespace] = ip.netns(namespace)

    # Create interfaces
    for namespace, values in config['namespaces'].items():
        ns = namespaces[namespace]

        if 'interfaces' not in values:
            values['interfaces'] = []

        for interface in values['interfaces']:
            if interface['type'] == 'veth':
                (iface1, iface2) = ns.ip.veth(namespaces[interface['peer']],
                                              interface['my_interface'],
                                              interface['their_interface'])
                iface1.up()
                iface2.up()
                if 'my_address' in interface:
                    iface1.add_address(interface['my_address'])
                if 'peer_address' in interface:
                    iface2.add_address(interface['peer_address'])
                if 'my_address6' in interface:
                    iface1.add_address(interface['my_address6'])
                if 'peer_address6' in interface:
                    iface2.add_address(interface['peer_address6'])
            elif interface['type'] == 'normal':
                iface = ns.ip.interface(interface['name'])
                iface.up()
                if 'address' in interface:
                    iface.add_address(interface['address'])
                if 'address6' in interface:
                    iface.add_address(interface['address6'])
            else:
                raise IPException("Unknown interface type %s" % interface['type'])

    # Create routes
    for namespace, values in config['namespaces'].items():
        ns = namespaces[namespace]
        for route in values['routes']:
            if len(route['nexthop']) > 1:
                # ECMP route
                ns.ip.ecmp_route(route['destination'], route['nexthop'], state="exists")
            else:
                ns.ip.route(route['destination'], route['nexthop'][0]['via'], state="exists")
        for route in values['routes6']:
            if len(route['nexthop']) > 1:
                # ECMP route
                ns.ip.ecmp_route6(route['destination'], route['nexthop'], state="exists")
            else:
                ns.ip.route6(route['destination'], route['nexthop'][0]['via'], state="exists")
    # Run commands
    for namespace, values in config['namespaces'].items():
        ns = namespaces[namespace]
        for run in values['run']:
            ns.ip.context.run(run['command'], *run['args'], background=run['background'])


def destroy_from_config(config):
    current_namespaces = [x.strip() for x in ip.context.run(IPCOMMAND, 'netns', 'list').splitlines()]
    for namespace in config['namespaces'].keys():
        if namespace == 'global':
            continue
        if namespace not in current_namespaces:
            continue
        for pid in ip.context.run(IPCOMMAND, 'netns', 'pids', namespace).splitlines():
            pid = pid.strip()
            ip.context.run('/bin/kill', pid)
        ip.netns_del(namespace)

    if 'global' in config['namespaces'].keys():
        if 'routes' in config['namespaces']['global']:
            for route in config['namespaces']['global']['routes']:
                if len(route['nexthop']) > 1:
                    ip.ecmp_route(route['destination'], route['nexthop'], state="absent")
                else:
                    ip.route(route['destination'], route['nexthop'][0]['via'], state="absent")

ip = IP()

if __name__ == '__main__':
    logging.basicConfig()
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--config", help="Config file", required=True)
    parser.add_argument("-d", "--debug", help="Enable debug", default=False, action="store_true")
    parser.add_argument('action', help="Action to do", default="create", choices=["create", "destroy", "dump"])

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    c = open(args.config, 'r')

    config = normalize_config(yaml.load(c.read()))

    logger.debug("Parsed configuration:\n%s" % yaml.dump(config))

    if args.action == 'create':
        create_from_config(config)
    elif args.action == 'destroy':
        destroy_from_config(config)
    elif args.action == 'dump':
        print(yaml.dump(config, indent=4, default_flow_style=False, default_style='"'))
    else:
        print("Invalid action %s" % args.action)
        sys.exit(1)
    logger.info("Done!")
