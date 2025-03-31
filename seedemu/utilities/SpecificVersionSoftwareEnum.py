#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2025/3/23 21:47
# @Author  : Yu.Jingkai
# @File    : SpecificVersionSoftwareEnum.py


from enum import Enum


class SpecificVersionSoftwareEnum(Enum):
    BIND = r'^bind-[a-z0-9.]+$'
    # UNBOUND = r'^unbound[a-z0-9.]+$'



# 使用枚举
# print(Color.RED)
# print(Color.GREEN.name)
# print(Color.BLUE.value)
