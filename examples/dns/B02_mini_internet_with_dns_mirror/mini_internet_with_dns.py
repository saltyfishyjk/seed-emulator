#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2025/2/24 22:40
# @Author  : Yu.Jingkai
# @File    : mini_internet_with_dns.py
# !/usr/bin/env python3
# encoding: utf-8

from seedemu.core import Emulator, Binding, Filter, Action
from seedemu.mergers import DEFAULT_MERGERS
from seedemu.compiler import Docker, Platform
from seedemu.services import DomainNameCachingService
from seedemu.services.DomainNameCachingService import DomainNameCachingServer
from seedemu.layers import Base
from examples.dns.B00_mini_internet_mirror import mini_internet
from examples.dns.B01_dns_component_mirror import dns_component
import os, sys


def run(dumpfile=None):
# def run(dumpfile='./mini_internet_with_dns.bin'):
    ###############################################################################
    # Set the platform information
    if dumpfile is None:
        script_name = os.path.basename(__file__)

        if len(sys.argv) == 1:
            platform = Platform.AMD64
        elif len(sys.argv) == 2:
            if sys.argv[1].lower() == 'amd':
                platform = Platform.AMD64
            elif sys.argv[1].lower() == 'arm':
                platform = Platform.ARM64
            else:
                print(f"Usage:  {script_name} amd|arm")
                sys.exit(1)
        else:
            print(f"Usage:  {script_name} amd|arm")
            sys.exit(1)

    emuA = Emulator()
    emuB = Emulator()

    # Run the pre-built components
    mini_internet.run(dumpfile='./base_internet.bin')
    dns_component.run(dumpfile='./dns_component.bin')

    # Load and merge the pre-built components
    emuA.load('./base_internet.bin')
    emuB.load('./dns_component.bin')
    emu = emuA.merge(emuB, DEFAULT_MERGERS)

    #####################################################################################
    # Bind the virtual nodes in the DNS infrastructure layer to physical nodes.
    # Action.FIRST will look for the first acceptable node that satisfies the filter rule.
    # There are several other filters types that are not shown in this example.

    emu.addBinding(Binding('a-root-server', filter=Filter(asn=171), action=Action.FIRST))
    # emu.addBinding(Binding('b-root-server', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('a-com-server', filter=Filter(asn=151), action=Action.FIRST))
    # emu.addBinding(Binding('b-com-server', filter=Filter(asn=152), action=Action.FIRST))
    emu.addBinding(Binding('a-net-server', filter=Filter(asn=152), action=Action.FIRST))
    emu.addBinding(Binding('a-edu-server', filter=Filter(asn=153), action=Action.FIRST))
    emu.addBinding(Binding('ns-twitter-com', filter=Filter(asn=161), action=Action.FIRST))
    emu.addBinding(Binding('ns-google-com', filter=Filter(asn=162), action=Action.FIRST))
    emu.addBinding(Binding('ns-example-net', filter=Filter(asn=163), action=Action.FIRST))
    emu.addBinding(Binding('ns-syr-edu', filter=Filter(asn=164), action=Action.FIRST))

    #####################################################################################
    # Create two local DNS servers (virtual nodes).
    ldns = DomainNameCachingService()
    global_dns_1: DomainNameCachingServer = ldns.install('global-dns-1')
    global_dns_2: DomainNameCachingServer = ldns.install('global-dns-2')

    # global_dns_1.setVersion('powerdns')
    # global_dns_1.setVersion('unbound')
    # global_dns_2: DomainNameCachingServer = ldns.install('global-dns-2')

    # Customize the display name (for visualization purpose)
    emu.getVirtualNode('global-dns-1').setDisplayName('Global DNS-1')
    emu.getVirtualNode('global-dns-2').setDisplayName('Global DNS-2')



    # Create two new host in AS-152 and AS-153, use them to host the local DNS server.
    # We can also host it on an existing node.

    dns_1_address = '10.152.0.53'
    dns_2_address = '10.153.0.53'

    base: Base = emu.getLayer('Base')
    as152 = base.getAutonomousSystem(152)
    as152.createHost('local-dns-1').joinNetwork('net0', address=dns_1_address)
    as153 = base.getAutonomousSystem(153)
    as153.createHost('local-dns-2').joinNetwork('net0', address=dns_2_address)

    global_dns_2.setForwardOnly(True)
    global_dns_2.setForwarders([dns_1_address])

    # Bind the Local DNS virtual nodes to physical nodes
    emu.addBinding(Binding('global-dns-1', filter=Filter(asn=152, nodeName="local-dns-1")))
    emu.addBinding(Binding('global-dns-2', filter=Filter(asn=153, nodeName="local-dns-2")))

    # Add 10.152.0.53 as the local DNS server for AS-160 and AS-170
    # Add 10.153.0.53 as the local DNS server for all the other nodes
    global_dns_1.setNameServerOnNodesByAsns(asns=[160, 170])
    # global_dns_1.setNameServerOnAllNodes()
    global_dns_2.setNameServerOnAllNodes()

    # Add the ldns layer
    emu.addLayer(ldns)

    if dumpfile is not None:
        # Save it to a file, so it can be used by other emulators
        emu.dump(dumpfile)
    else:
        # Rendering compilation
        emu.render()
        emu.compile(Docker(platform=platform), './output', override=True)


if __name__ == "__main__":
    run()

