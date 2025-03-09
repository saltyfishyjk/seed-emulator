#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2025/2/24 22:43
# @Author  : Yu.Jingkai
# @File    : dns_component.py
# !/usr/bin/env python3
# encoding: utf-8

from seedemu.core import Emulator
from seedemu.services import DomainNameService, DomainNameCachingService


def run(dumpfile=None):
    emu = Emulator()

    ###########################################################
    # Create a DNS layer
    dns = DomainNameService()

    # Create two nameservers for the root zone
    dns.install('a-root-server').addZone('.').setMaster()  # Master server
    # dns.install('b-root-server').addZone('.')  # Slave server

    # Create nameservers for TLD and ccTLD zones
    dns.install('a-com-server').addZone('com.').setMaster()

    print(dns.getAllServerNames())

    # dns.install('b-com-server').addZone('com.')
    a_net_server = dns.install('a-net-server')
    a_net_server.addZone('net.')
    a_net_server.setVersion('unbound')
    # a_net_server_node = a_net_server.getNode()
    dns.install('a-edu-server').addZone('edu.')

    # Create nameservers for second-level zones
    dns.install('ns-twitter-com').addZone('twitter.com.')
    dns.install('ns-google-com').addZone('google.com.')
    dns.install('ns-example-net').addZone('example.net.')
    dns.install('ns-syr-edu').addZone('syr.edu.')

    # Add records to zones
    # dns.getZone('twitter.com.').addRecord('@ A 1.1.1.1')
    # dns.getZone('google.com.').addRecord('@ A 2.2.2.2')
    # dns.getZone('example.net.').addRecord('@ A 3.3.3.3')
    # dns.getZone('syr.edu.').addRecord('@ A 128.230.18.63')

    # Customize the display names (for visualization purpose)
    emu.getVirtualNode('a-root-server').setDisplayName('Root-A')
    # emu.getVirtualNode('b-root-server').setDisplayName('Root-B')
    emu.getVirtualNode('a-com-server').setDisplayName('COM-A')
    # emu.getVirtualNode('b-com-server').setDisplayName('COM-B')
    emu.getVirtualNode('a-net-server').setDisplayName('NET')
    emu.getVirtualNode('a-edu-server').setDisplayName('EDU')
    emu.getVirtualNode('ns-twitter-com').setDisplayName('twitter.com')
    emu.getVirtualNode('ns-google-com').setDisplayName('google.com')
    emu.getVirtualNode('ns-example-net').setDisplayName('example.net')
    emu.getVirtualNode('ns-syr-edu').setDisplayName('syr.edu')

    ###########################################################
    emu.addLayer(dns)

    if dumpfile is not None:
        emu.dump(dumpfile)
    else:
        emu.dump('dns_component.bin')


if __name__ == "__main__":
    run()
