#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2025/2/23 20:09
# @Author  : Yu.Jingkai
# @File    : dnshound_simple.py


from seedemu.compiler import Docker, Platform
from seedemu.core import Emulator, Binding, Filter, Action
from seedemu.layers import Base, Ebgp, Ibgp, Ospf, Routing, PeerRelationship, EtcHosts
from seedemu.services import DomainNameService, DomainNameCachingService
from seedemu.services.DomainNameCachingService import DomainNameCachingServer
from seedemu.utilities import Makers
import os, sys


def run(dumpfile=None):
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

    emu = Emulator()
    base = Base()
    dns = DomainNameService()

    # Create two nameservers for the root zone
    dns.install('a-root-server').addZone('.').setMaster()   # Master server
    dns.install('b-root-server').addZone('.')               # Slave server

    # Create nameservers for TLD and ccTLD zones
    dns.install('a-com-server').addZone('com.').setMaster()
    dns.install('b-com-server').addZone('com.')
    dns.install('a-net-server').addZone('net.')
    dns.install('a-edu-server').addZone('edu.')

    # Create nameservers for second-level zones
    dns.install('ns-twitter-com').addZone('twitter.com.')
    dns.install('ns-google-com').addZone('google.com.')
    dns.install('ns-example-net').addZone('example.net.')
    dns.install('ns-syr-edu').addZone('syr.edu.')


    # Add records to zones
    dns.getZone('twitter.com.').addRecord('@ A 1.1.1.1')
    dns.getZone('google.com.').addRecord('@ A 2.2.2.2')
    dns.getZone('example.net.').addRecord('@ A 3.3.3.3')
    dns.getZone('syr.edu.').addRecord('@ A 128.230.18.63')

    # Customize the display names (for visualization purpose)
    emu.getVirtualNode('a-root-server').setDisplayName('Root-A')
    emu.getVirtualNode('b-root-server').setDisplayName('Root-B')
    emu.getVirtualNode('a-com-server').setDisplayName('COM-A')
    emu.getVirtualNode('b-com-server').setDisplayName('COM-B')
    emu.getVirtualNode('a-net-server').setDisplayName('NET')
    emu.getVirtualNode('a-edu-server').setDisplayName('EDU')
    emu.getVirtualNode('ns-twitter-com').setDisplayName('twitter.com')
    emu.getVirtualNode('ns-google-com').setDisplayName('google.com')
    emu.getVirtualNode('ns-example-net').setDisplayName('example.net')
    emu.getVirtualNode('ns-syr-edu').setDisplayName('syr.edu')

    ###########################################################

    ix100 = base.createInternetExchange(100)

    ix100.getPeeringLan().setDisplayName('NYC-100')
    Makers.makeStubAsWithHosts(emu, base, 150, 100, 15)
    # as150 = base.createAutonomousSystem(150)
    as150 = base.getAutonomousSystem(150)
    # as150.createNetwork('net0')
    # as150.createRouter('router0').joinNetwork('net0').joinNetwork('ix100')
    # for i in range(6):
    #     host = as150.createHost('host_{}'.format(i)).joinNetwork('net0')

    emu.addLayer(base)
    emu.addLayer(EtcHosts())
    emu.addLayer(dns)

    emu.addBinding(Binding('a-root-server', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('b-root-server', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('a-com-server', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('b-com-server', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('a-net-server', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('a-edu-server', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('ns-twitter-com', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('ns-google-com', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('ns-example-net', filter=Filter(asn=150), action=Action.FIRST))
    emu.addBinding(Binding('ns-syr-edu', filter=Filter(asn=150), action=Action.FIRST))

    ###########################################################

    if dumpfile is not None:
        emu.dump(dumpfile)
    else:
        emu.render()
        emu.compile(Docker(platform=platform), './output', override=True)


if __name__ == "__main__":
    run()
