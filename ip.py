
import subprocess
import string
import random
import sys
import os
import yaml
import logging


logger = logging.getLogger("ipns")

IPCOMMAND = '/bin/ip'
KILLCOMMAND = '/bin/kill'
SYSCTLCOMMAND = '/sbin/sysctl'


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
            self.context.run(SYSCTLCOMMAND, '-w', 'net.ipv4.ip_forward=1')
            self.context.run(SYSCTLCOMMAND, '-w', 'net.ipv4.conf.all.forwarding=1')
            self.context.run(SYSCTLCOMMAND, '-w', 'net.ipv6.conf.all.forwarding=1')


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

    def veth(self, other, my_interface, peer_interface):
        """
        Create virtual ethernet interface between this and other namespace
        :param other: Another namespace where other end of veth is located
        :return: Tuple containing two interfaces
        """
        other_name = other.name
        if other_name == "global":
            other_name = "1"
        self.context.run(IPCOMMAND, 'link', 'add', my_interface, 'type', 'veth', 'peer', 'name', peer_interface)
        self.context.run(IPCOMMAND  , 'link', 'set', peer_interface, 'netns', other_name)
        return self.interface(my_interface), other.ip.interface(peer_interface)

ip = IP()

class NetNS(object):
    def __init__(self, name):
        self.name = name
        if name == "global":
            nsname = None
        else:
            nsname = name
        self.ip = IP(namespace=nsname)
