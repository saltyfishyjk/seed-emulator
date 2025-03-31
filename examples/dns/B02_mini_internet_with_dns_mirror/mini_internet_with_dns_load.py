#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2025/3/1 10:53
# @Author  : Yu.Jingkai
# @File    : mini_internet_with_dns_load.py

from seedemu.core import Emulator
from seedemu.compiler import Docker, Platform
import os, sys

def run(dumpfile=None):
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

    emu = Emulator()
    emu.load('./mini_internet_with_dns.bin')
    print("Load successful")
    emu.render()
    emu.compile(Docker(platform=platform), './load_output', override=True)


if __name__ == "__main__":
    run("./mini_internet_with_dns.bin")
