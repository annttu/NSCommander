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

import subprocess
import string
import random
import yaml


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

    def run(self, *args, **kwargs):
        command = self._ns_prefix() + list(args)
        print(command)
        p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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

    def route(self, destination, nexthop, state="exists"):
        routes = [x.split()[0] for x in self.context.run(IPCOMMAND, 'route', 'list').splitlines()]
        if state == "exists":
            if destination not in routes:
                self.context.run(IPCOMMAND, 'route', 'add', destination, 'via', nexthop)
        elif state == "absent":
            if destination in routes:
                self.context.run(IPCOMMAND, 'route', 'delete', destination, 'via', nexthop)

    def ecmp_route(self, destination, nexthops, state="exists"):
        routes = [x.split()[0] for x in self.context.run(IPCOMMAND, 'route', 'list').splitlines()]
        if state == "exists":
            if destination not in routes:
                cmd = []
                for nexthop in nexthops:
                    cmd += ['nexthop', 'via', nexthop['via']]
                    if 'weight' in nexthop:
                        cmd += ['weight', str(nexthop['weight'])]
                    if 'interface' in nexthop:
                        cmd += ['interface', str(nexthop['interface'])]
                self.context.run(IPCOMMAND, 'route', 'add', destination, *cmd)
        elif state == "absent":
            if destination in routes:
                self.context.run(IPCOMMAND, 'route', 'delete', destination)

    def netns_list(self):
        return [x.strip() for x in self.context.run(IPCOMMAND, 'netns', 'list').splitlines()]

    def netns_add(self, name):
        if not name:
            raise IPException("Invalid empty namespace name")
        if name not in self.netns_list():
            self.context.run(IPCOMMAND, 'netns', 'add', name)

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

    def veth(self, other, prefix="veth-"):
        """
        Create virtual ethernet interface between this and other namespace
        :param other: Another namespace where other end of veth is located
        :return: Tuple containing two interfaces
        """
        if len(prefix) > 13:
            prefix = prefix[:13]
        name = random_string(prefix, length=13 - len(prefix))
        my_interface = '%s-a' % name
        their_interface = '%s-b' % name
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


def normalize_config(config):
    if 'namespaces' not in config:
        config['namespaces'] = []
    for name, namespace in config['namespaces'].items():
        if 'routes' not in namespace:
            namespace['routes'] = []
        if 'interfaces' not in namespace:
            namespace['interfaces'] = []
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

        for interface in namespace['interfaces']:
            if 'type' not in interface:
                interface['type'] = "normal"
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
            if 'type' not in interface:
                interface['type'] = 'normal'
            if interface['type'] == 'veth':
                (iface1, iface2) = ns.ip.veth(namespaces[interface['peer']])
                iface1.up()
                iface2.up()
                if 'my_address' in interface:
                    iface1.add_address(interface['my_address'])
                if 'peer_address' in interface:
                    iface2.add_address(interface['peer_address'])
            elif interface['type'] == 'normal':
                iface = ns.ip.interface(interface['name'])
                iface.up()
                if 'address' in interface:
                    iface.add_address(interface['address'])

    # Create routes
    for namespace, values in config['namespaces'].items():
        ns = namespaces[namespace]
        if 'routes' not in values:
            values['routes'] = []
        for route in values['routes']:
            if 'destination' not in route:
                raise IPException("Invalid route, destination missing")
            if 'nexthop' not in route:
                raise IPException("Invalid route, nexthop missing")
            if type(route['nexthop']) == str:
                route['nexthop'] = [{'via': route['nexthop']}]
            if len(route['nexthop']) > 1:
                # ECMP route
                ns.ip.ecmp_route(route['destination'], route['nexthop'], state="exists")
            else:
                ns.ip.route(route['destination'], route['nexthop'][0]['via'], state="exists")


def destroy_from_config(config):
    for namespace in config['namespaces'].keys():
        if namespace == 'global':
            continue
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
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--config", help="Config file", required=True)
    parser.add_argument('action', help="Action to do", default="create", choices=["create", "destroy"])

    args = parser.parse_args()

    c = open(args.config, 'r')

    config = normalize_config(yaml.load(c.read()))

    print(yaml.dump(config))

    if args.action == 'create':
        create_from_config(config)
    else:
        destroy_from_config(config)
