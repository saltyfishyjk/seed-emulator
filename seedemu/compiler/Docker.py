from __future__ import annotations
from seedemu.core.Emulator import Emulator
from seedemu.core import Node, Network, Compiler, BaseSystem
from seedemu.core.enums import NodeRole, NetworkType
from .DockerImage import DockerImage
from seedemu.utilities.SpecificVersionSoftwareEnum import SpecificVersionSoftwareEnum
from .DockerImageConstant import *
from typing import Dict, Generator, List, Set, Tuple
from hashlib import md5
from os import mkdir, chdir
from re import sub
from ipaddress import IPv4Network, IPv4Address
from shutil import copyfile
import json
import re


SEEDEMU_INTERNET_MAP_IMAGE='handsonsecurity/seedemu-multiarch-map:buildx-latest'
SEEDEMU_ETHER_VIEW_IMAGE='handsonsecurity/seedemu-multiarch-etherview:buildx-latest'

DockerCompilerFileTemplates: Dict[str, str] = {}

DockerCompilerFileTemplates['dockerfile'] = """\
ARG DEBIAN_FRONTEND=noninteractive
"""
#RUN echo 'exec zsh' > /root/.bashrc

DockerCompilerFileTemplates['start_script'] = """\
#!/bin/bash
{startCommands}
echo "ready! run 'docker exec -it $HOSTNAME /bin/zsh' to attach to this node" >&2
for f in /proc/sys/net/ipv4/conf/*/rp_filter; do echo 0 > "$f"; done
tail -f /dev/null
"""

DockerCompilerFileTemplates['seedemu_sniffer'] = """\
#!/bin/bash
last_pid=0
while read -sr expr; do {
    [ "$last_pid" != 0 ] && kill $last_pid 2> /dev/null
    [ -z "$expr" ] && continue
    tcpdump -e -i any -nn -p -q "$expr" &
    last_pid=$!
}; done
[ "$last_pid" != 0 ] && kill $last_pid
"""

DockerCompilerFileTemplates['seedemu_worker'] = """\
#!/bin/bash

net() {
    [ "$1" = "status" ] && {
        ip -j link | jq -cr '.[] .operstate' | grep -q UP && echo "up" || echo "down"
        return
    }

    ip -j li | jq -cr '.[] .ifname' | while read -r ifname; do ip link set "$ifname" "$1"; done
}

bgp() {
    cmd="$1"
    peer="$2"
    [ "$cmd" = "bird_peer_down" ] && birdc dis "$2"
    [ "$cmd" = "bird_peer_up" ] && birdc en "$2"
}

while read -sr line; do {
    id="`cut -d ';' -f1 <<< "$line"`"
    cmd="`cut -d ';' -f2 <<< "$line"`"

    output="no such command."

    [ "$cmd" = "net_down" ] && output="`net down 2>&1`"
    [ "$cmd" = "net_up" ] && output="`net up 2>&1`"
    [ "$cmd" = "net_status" ] && output="`net status 2>&1`"
    [ "$cmd" = "bird_list_peer" ] && output="`birdc s p | grep --color=never BGP 2>&1`"

    [[ "$cmd" == "bird_peer_"* ]] && output="`bgp $cmd 2>&1`"

    printf '_BEGIN_RESULT_'
    jq -Mcr --arg id "$id" --arg return_value "$?" --arg output "$output" -n '{id: $id | tonumber, return_value: $return_value | tonumber, output: $output }'
    printf '_END_RESULT_'
}; done
"""

DockerCompilerFileTemplates['replace_address_script'] = '''\
#!/bin/bash
ip -j addr | jq -cr '.[]' | while read -r iface; do {
    ifname="`jq -cr '.ifname' <<< "$iface"`"
    jq -cr '.addr_info[]' <<< "$iface" | while read -r iaddr; do {
        addr="`jq -cr '"\(.local)/\(.prefixlen)"' <<< "$iaddr"`"
        line="`grep "$addr" < /dummy_addr_map.txt`"
        [ -z "$line" ] && continue
        new_addr="`cut -d, -f2 <<< "$line"`"
        ip addr del "$addr" dev "$ifname"
        ip addr add "$new_addr" dev "$ifname"
    }; done
}; done
'''

DockerCompilerFileTemplates['compose'] = """\
version: "3.4"
services:
{dummies}
{services}
networks:
{networks}
"""

DockerCompilerFileTemplates['compose_dummy'] = """\
    {imageDigest}:
        build:
            context: .
            dockerfile: dummies/{imageDigest}
        image: {imageDigest}
{dependsOn}
"""

DockerCompilerFileTemplates['depends_on'] = """\
        depends_on:
            - {dependsOn}
"""

DockerCompilerFileTemplates['compose_service'] = """\
    {nodeId}:
        build: ./{nodeId}
        container_name: {nodeName}
        depends_on:
            - {dependsOn}
        cap_add:
            - ALL
        sysctls:
            - net.ipv4.ip_forward=1
            - net.ipv4.conf.default.rp_filter=0
            - net.ipv4.conf.all.rp_filter=0
        privileged: true
        networks:
{networks}{ports}{volumes}
        labels:
{labelList}
"""

DockerCompilerFileTemplates['compose_label_meta'] = """\
            org.seedsecuritylabs.seedemu.meta.{key}: "{value}"
"""

DockerCompilerFileTemplates['compose_ports'] = """\
        ports:
{portList}
"""

DockerCompilerFileTemplates['compose_port'] = """\
            - {hostPort}:{nodePort}/{proto}
"""

DockerCompilerFileTemplates['compose_volumes'] = """\
        volumes:
{volumeList}
"""

DockerCompilerFileTemplates['compose_volume'] = """\
            - type: bind
              source: {hostPath}
              target: {nodePath}
"""

DockerCompilerFileTemplates['compose_storage'] = """\
            - {nodePath}
"""

DockerCompilerFileTemplates['compose_service_network'] = """\
            {netId}:
{address}
"""

DockerCompilerFileTemplates['compose_service_network_address'] = """\
                ipv4_address: {address}
"""

DockerCompilerFileTemplates['compose_network'] = """\
    {netId}:
        driver_opts:
            com.docker.network.driver.mtu: {mtu}
        ipam:
            config:
                - subnet: {prefix}
        labels:
{labelList}
"""

DockerCompilerFileTemplates['seedemu_internet_map'] = """\
    seedemu-internet-client:
        image: {clientImage}
        container_name: seedemu_internet_map
        volumes:
            - /var/run/docker.sock:/var/run/docker.sock
        ports:
            - {clientPort}:8080/tcp
"""

DockerCompilerFileTemplates['seedemu_ether_view'] = """\
    seedemu-ether-client:
        image: {clientImage}
        container_name: seedemu_ether_view
        volumes:
            - /var/run/docker.sock:/var/run/docker.sock
        ports:
            - {clientPort}:5000/tcp
"""

DockerCompilerFileTemplates['zshrc_pre'] = """\
export NOPRECMD=1
alias st=set_title
"""

DockerCompilerFileTemplates['local_image'] = """\
    {imageName}:
        build:
            context: {dirName}
        image: {imageName}
"""

# class DockerImage(object):
#     """!
#     @brief The DockerImage class.

#     This class represents a candidate image for docker compiler.
#     """

#     __software: Set[str]
#     __name: str
#     __local: bool
#     __dirName: str

#     def __init__(self, name: str, software: List[str], local: bool = False, dirName: str = None) -> None:
#         """!
#         @brief create a new docker image.

#         @param name name of the image. Can be name of a local image, image on
#         dockerhub, or image in private repo.
#         @param software set of software pre-installed in the image, so the
#         docker compiler can skip them when compiling.
#         @param local (optional) set this image as a local image. A local image
#         is built locally instead of pulled from the docker hub. Default to False.
#         @param dirName (optional) directory name of the local image (when local
#         is True). Default to None. None means use the name of the image.
#         """
#         super().__init__()

#         self.__name = name
#         self.__software = set()
#         self.__local = local
#         self.__dirName = dirName if dirName != None else name

#         for soft in software:
#             self.__software.add(soft)

#     def getName(self) -> str:
#         """!
#         @brief get the name of this image.

#         @returns name.
#         """
#         return self.__name

#     def getSoftware(self) -> Set[str]:
#         """!
#         @brief get set of software installed on this image.
        
#         @return set.
#         """
#         return self.__software
#     def getDirName(self) -> str:
#         """!
#         @brief returns the directory name of this image.
#         @return directory name.
#         """
#         return self.__dirName
    
#     def isLocal(self) -> bool:
#         """!
#         @brief returns True if this image is local.

#         @return True if this image is local.
#         """
#         return self.__local
    
#     def addSoftwares(self, software) -> DockerImage:
#         """!
#         @brief add softwares to this image.
#         @return self, for chaining api calls.
#         """
#         for soft in software:
#             self.__software.add(soft)


class Docker(Compiler):
    """!
    @brief The Docker compiler class.

    Docker is one of the compiler driver. It compiles the lab to docker
    containers.
    """

    __services: str
    __networks: str
    __naming_scheme: str
    __self_managed_network: bool
    __dummy_network_pool: Generator[IPv4Network, None, None]

    __internet_map_enabled: bool
    __internet_map_port: int

    __ether_view_enabled: bool
    __ether_view_port: int

    __client_hide_svcnet: bool

    __images: Dict[str, Tuple[DockerImage, int]]
    __forced_image: str
    __disable_images: bool
    __image_per_node_list: Dict[Tuple[str, str], DockerImage]
    _used_images: Set[str]

    __basesystem_dockerimage_mapping: dict

    def __init__(
        self,
        platform:Platform = Platform.AMD64,
        namingScheme: str = "as{asn}{role}-{displayName}-{primaryIp}",
        selfManagedNetwork: bool = False,
        dummyNetworksPool: str = '10.128.0.0/9',
        dummyNetworksMask: int = 24,
        internetMapEnabled: bool = True,
        internetMapPort: int = 8080,
        etherViewEnabled: bool = False,
        etherViewPort: int = 5000,
        clientHideServiceNet: bool = True
    ):
        """!
        @brief Docker compiler constructor.

        @param platform (optional) node cpu architecture Default to Platform.AMD64
        @param namingScheme (optional) node naming scheme. Available variables
        are: {asn}, {role} (r - router, h - host, rs - route server), {name},
        {primaryIp} and {displayName}. {displayName} will automatically fall
        back to {name} if
        Default to as{asn}{role}-{displayName}-{primaryIp}.
        @param selfManagedNetwork (optional) use self-managed network. Enable
        this to manage the network inside containers instead of using docker's
        network management. This works by first assigning "dummy" prefix and
        address to containers, then replace those address with "real" address
        when the containers start. This will allow the use of overlapping
        networks in the emulation and will allow the use of the ".1" address on
        nodes. Note this will break port forwarding (except for service nodes
        like real-world access node and remote access node.) Default to False.
        @param dummyNetworksPool (optional) dummy networks pool. This should not
        overlap with any "real" networks used in the emulation, including
        loopback IP addresses. Default to 10.128.0.0/9.
        @param dummyNetworksMask (optional) mask of dummy networks. Default to
        24.
        @param internetMapEnabled (optional) set if seedemu internetMap should be enabled.
        Default to False. Note that the seedemu internetMap allows unauthenticated
        access to all nodes, which can potentially allow root access to the
        emulator host. Only enable seedemu in a trusted network.
        @param internetMapPort (optional) set seedemu internetMap port. Default to 8080.
        @param etherViewEnabled (optional) set if seedemu EtherView should be enabled.
        Default to False.
        @param etherViewPort (optional) set seedemu EtherView port. Default to 5000.
        @param clientHideServiceNet (optional) hide service network for the
        client map by not adding metadata on the net. Default to True.
        """
        self.__networks = ""
        self.__services = ""
        self.__naming_scheme = namingScheme
        self.__self_managed_network = selfManagedNetwork
        self.__dummy_network_pool = IPv4Network(dummyNetworksPool).subnets(new_prefix = dummyNetworksMask)

        self.__internet_map_enabled = internetMapEnabled
        self.__internet_map_port = internetMapPort

        self.__ether_view_enabled = etherViewEnabled
        self.__ether_view_port = etherViewPort

        self.__client_hide_svcnet = clientHideServiceNet

        self.__images = {}
        self.__forced_image = None
        self.__disable_images = False
        self._used_images = set()
        self.__image_per_node_list = {}

        self.__platform = platform

        self.__basesystem_dockerimage_mapping = BASESYSTEM_DOCKERIMAGE_MAPPING_PER_PLATFORM[self.__platform]
        
        for name, image in self.__basesystem_dockerimage_mapping.items():
            priority = 0
            if name == BaseSystem.DEFAULT:
                priority = 1
            self.addImage(image, priority=priority)
        

    def getName(self) -> str:
        return "Docker"

    def addImage(self, image: DockerImage, priority: int = -1) -> Docker:
        """!
        @brief add an candidate image to the compiler.

        @param image image to add.
        @param priority (optional) priority of this image. Used when one or more
        images with same number of missing software exist. The one with highest
        priority wins. If two or more images with same priority and same number
        of missing software exist, the one added the last will be used. All
        built-in images has priority of 0. Default to -1. All built-in images are
        prior to the added candidate image. To set a candidate image to a node,
        use setImageOverride() method.

        @returns self, for chaining api calls.
        """
        assert image.getName() not in self.__images, 'image with name {} already exists.'.format(image.getName())

        self.__images[image.getName()] = (image, priority)

        return self

    def getImages(self) -> List[Tuple[DockerImage, int]]:
        """!
        @brief get list of images configured.

        @returns list of tuple of images and priority.
        """

        return list(self.__images.values())

    def forceImage(self, imageName: str) -> Docker:
        """!
        @brief forces the docker compiler to use a image, identified by the
        imageName. Image with such name must be added to the docker compiler
        with the addImage method, or the docker compiler will fail at compile
        time. Set to None to disable the force behavior.

        @param imageName name of the image.

        @returns self, for chaining api calls.
        """
        self.__forced_image = imageName

        return self

    def disableImages(self, disabled: bool = True) -> Docker:
        """!
        @brief forces the docker compiler to not use any images and build
        everything for starch. Set to False to disable the behavior.

        @param disabled (option) disabled image if True. Default to True.

        @returns self, for chaining api calls.
        """
        self.__disable_images = disabled

        return self

    def setImageOverride(self, node:Node, imageName:str) -> Docker:
        """!
        @brief set the docker compiler to use a image on the specified Node.

        @param node target node to override image.
        @param imageName name of the image to use.

        @returns self, for chaining api calls.
        """
        asn = node.getAsn()
        name = node.getName()
        self.__image_per_node_list[(asn, name)]=imageName

    def _groupSoftware(self, emulator: Emulator):
        """!
        @brief Group apt-get install calls to maximize docker cache.

        @param emulator emulator to load nodes from.
        """

        registry = emulator.getRegistry()

        # { [imageName]: { [softName]: [nodeRef] } }
        softGroups: Dict[str, Dict[str, List[Node]]] = {}

        # { [imageName]: useCount }
        groupIter: Dict[str, int] = {}

        for ((scope, type, name), obj) in registry.getAll().items():
            if type not in ['rnode', 'csnode', 'hnode', 'snode', 'rs', 'snode']:
                continue

            node: Node = obj

            (img, _) = self._selectImageFor(node)
            imgName = img.getName()

            if not imgName in groupIter:
                groupIter[imgName] = 0

            groupIter[imgName] += 1

            if not imgName in softGroups:
                softGroups[imgName] = {}

            group = softGroups[imgName]

            for soft in node.getSoftware():
                if soft not in group:
                    group[soft] = []
                group[soft].append(node)

        for (key, val) in softGroups.items():
            maxIter = groupIter[key]
            self._log('grouping software for image "{}" - {} references.'.format(key, maxIter))
            step = 1

            for commRequired in range(maxIter, 0, -1):
                currentTier: Set[str] = set()
                currentTierNodes: Set[Node] = set()

                for (soft, nodes) in val.items():
                    if len(nodes) == commRequired:
                        currentTier.add(soft)
                        for node in nodes: currentTierNodes.add(node)

                for node in currentTierNodes:
                    if not node.hasAttribute('__soft_install_tiers'):
                        node.setAttribute('__soft_install_tiers', [])

                    node.getAttribute('__soft_install_tiers').append(currentTier)


                if len(currentTier) > 0:
                    self._log('the following software has been grouped together in step {}: {} since they are referenced by {} nodes.'.format(step, currentTier, len(currentTierNodes)))
                    step += 1


    def _selectImageFor(self, node: Node) -> Tuple[DockerImage, Set[str]]:
        """!
        @brief select image for the given node.

        @param node node.

        @returns tuple of selected image and set of missing software.
        """
        nodeSoft = node.getSoftware()
        nodeKey = (node.getAsn(), node.getName())

        # #1 Highest Priority (User Custom Image)
        if nodeKey in self.__image_per_node_list:
            image_name = self.__image_per_node_list[nodeKey]

            assert image_name in self.__images, 'image-per-node configured, but image {} does not exist.'.format(image_name)

            (image, _) = self.__images[image_name]

            self._log('image-per-node configured, using {}'.format(image.getName()))
            return (image, nodeSoft - image.getSoftware())

        # Should we keep this feature?
        if self.__disable_images:
            self._log('disable-imaged configured, using base image.')
            (image, _) = self.__images['ubuntu:20.04']
            return (image, nodeSoft - image.getSoftware())

        # Set Default Image for All Nodes
        if self.__forced_image != None:
            assert self.__forced_image in self.__images, 'forced-image configured, but image {} does not exist.'.format(self.__forced_image)

            (image, _) = self.__images[self.__forced_image]

            self._log('force-image configured, using image: {}'.format(image.getName()))

            return (image, nodeSoft - image.getSoftware())
            
        #Maintain a table : Virtual Image Name - Actual Image Name 
        image = self.__basesystem_dockerimage_mapping[node.getBaseSystem()]

        return (image, nodeSoft - image.getSoftware())
        
        # candidates: List[Tuple[DockerImage, int]] = []
        # minMissing = len(nodeSoft)
        # for (image, prio) in self.__images.values():
        #     missing = len(nodeSoft - image.getSoftware())

        #     if missing < minMissing:
        #         candidates = []
        #         minMissing = missing
        #     if missing <= minMissing: 
        #         candidates.append((image, prio))
        
        # assert len(candidates) > 0, '_electImageFor ended w/ no images?'

        # (selected, maxPrio) = candidates[0]

        # for (candidate, prio) in candidates:
        #     if prio >= maxPrio:
        #         maxPrio = prio
        #         selected = candidate

        # return (selected, nodeSoft - selected.getSoftware())


    def _getNetMeta(self, net: Network) -> str:
        """!
        @brief get net metadata labels.

        @param net net object.

        @returns metadata labels string.
        """

        (scope, type, name) = net.getRegistryInfo()

        labels = ''

        if self.__client_hide_svcnet and scope == 'seedemu' and name == '000_svc':
            return DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'dummy',
                value = 'dummy label for hidden node/net'
            )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'type',
            value = 'global' if scope == 'ix' else 'local'
        )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'scope',
            value = scope
        )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'name',
            value = name
        )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'prefix',
            value = net.getPrefix()
        )

        if net.getDisplayName() != None:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'displayname',
                value = net.getDisplayName()
            )

        if net.getDescription() != None:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'description',
                value = net.getDescription()
            )

        return labels

    def _getNodeMeta(self, node: Node) -> str:
        """!
        @brief get node metadata labels.

        @param node node object.

        @returns metadata labels string.
        """
        (scope, type, name) = node.getRegistryInfo()

        labels = ''

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'asn',
            value = node.getAsn()
        )

        labels += DockerCompilerFileTemplates['compose_label_meta'].format(
            key = 'nodename',
            value = name
        )

        if type == 'hnode':
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'role',
                value = 'Host'
            )

        if type == 'rnode':
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'role',
                value = 'Router'
            )

        if type == 'csnode':
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'role',
                value = 'SCION Control Service'
            )

        if type == 'snode':
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'role',
                value = 'Emulator Service Worker'
            )

        if type == 'rs':
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'role',
                value = 'Route Server'
            )

        if node.getDisplayName() != None:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'displayname',
                value = node.getDisplayName()
            )

        if node.getDescription() != None:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'description',
                value = node.getDescription()
            )

        if len(node.getClasses()) > 0:
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'class',
                value = json.dumps(node.getClasses()).replace("\"", "\\\"")
            )

        for key, value in node.getLabel().items():
            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = key,
                value = value
            )
        n = 0
        for iface in node.getInterfaces():
            net = iface.getNet()

            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'net.{}.name'.format(n),
                value = net.getName()
            )

            labels += DockerCompilerFileTemplates['compose_label_meta'].format(
                key = 'net.{}.address'.format(n),
                value = '{}/{}'.format(iface.getAddress(), net.getPrefix().prefixlen)
            )

            n += 1

        return labels

    def _nodeRoleToString(self, role: NodeRole):
        """!
        @brief convert node role to prefix string

        @param role node role

        @returns prefix string
        """
        if role == NodeRole.Host: return 'h'
        if role == NodeRole.Router: return 'r'
        if role == NodeRole.RouteServer: return 'rs'
        assert False, 'unknown node role {}'.format(role)

    def _contextToPrefix(self, scope: str, type: str) -> str:
        """!
        @brief Convert context to prefix.

        @param scope scope.
        @param type type.

        @returns prefix string.
        """
        return '{}_{}_'.format(type, scope)

    def _addFile(self, path: str, content: str) -> str:
        """!
        @brief Stage file to local folder and return Dockerfile command.

        @param path path to file. (in container)
        @param content content of the file.

        @returns COPY expression for dockerfile.
        """

        staged_path = md5(path.encode('utf-8')).hexdigest()
        print(content, file=open(staged_path, 'w'))
        return 'COPY {} {}\n'.format(staged_path, path)

    def _importFile(self, path: str, hostpath: str) -> str:
        """!
        @brief Stage file to local folder and return Dockerfile command.

        @param path path to file. (in container)
        @param hostpath path to file. (on host)

        @returns COPY expression for dockerfile.
        """

        staged_path = md5(path.encode('utf-8')).hexdigest()
        copyfile(hostpath, staged_path)
        return 'COPY {} {}\n'.format(staged_path, path)


    # 分发器，将需要特定安装的软件
    def _compileSpecificVersionSoftwareForDocker(self, soft: str) -> str:
        """!
        @brief Compile specific version software for docker.

        @param soft software name.

        @returns compiled software name.
        """
        ret = ''
        for enum_member in SpecificVersionSoftwareEnum:
            if re.match(enum_member.value, soft):
                # 找到匹配的软件
                # bind
                if enum_member == SpecificVersionSoftwareEnum.BIND:
                    ret = self._compileSpecificVersionBindForDocker(soft)
                # unbound TODO
                # powerdns TODO
        return ret

    # TODO 检查bind的/etc/named.conf
    def _compileSpecificVersionBindForDocker(self, soft: str) -> str:
        """!
        @brief Compile specific version bind for docker.

        @param soft software name.

        @returns compiled software name.
        """
        ret = ''
        # 设置环境变量，避免交互式提示
        ret = ret + 'ENV DEBIAN_FRONTEND=noninteractive\n\n'
        # 安装编译BIND所需的工具和库
        ret = ret + 'RUN apt-get update && apt-get install -y \\\n\
    build-essential \\\n\
    libssl-dev \\\n\
    wget \\\n\
    bison \\\n\
    pkg-config \\\n\
    liburcu-dev \\\n\
    libuv1 \\\n\
    libuv1-dev \\\n\
    libnghttp2-dev \\\n\
    libcap-dev \\\n\
    && apt-get clean \\\n\
    && rm -rf /var/lib/apt/lists/*\n\n'

        # 创建 bind 用户和组
        ret = ret + 'RUN groupadd -r named && useradd -r -g named named\n\n'

        bind4_pattern = r'^bind-4([a-zA-Z0-9.]+)$'  # 形如bind-4.1.1
        bind8_pattern = r'^bind-8([a-zA-Z0-9.]+)$'  # 形如bind-8.1.1
        bind9_pattern = r'^bind-(9[a-zA-Z0-9.]+)$'  # 形如bind-9.1.1
        bind10_pattern = r'^bind-10([a-zA-Z0-9.]+)$'  # 形如bind-10.1.1

        if re.match(bind4_pattern, soft):
            # TODO
            return 'bind4'
        elif re.match(bind8_pattern, soft):
            # TODO
            return 'bind9'
        elif re.match(bind9_pattern, soft):
            match = re.match(bind9_pattern, soft)
            version = match.group(1)
            #         ret = ret + f'RUN wget https://ftp.isc.org/isc/bind9/{version}/{soft}.tar.gz && \\\n\
            # tar -xzvf {soft}.tar.gz && \\\n\
            # cd {soft} && \\\n\
            # ./configure --prefix=/usr/local/named --enable-threads && \\\n\
            # make && \\\n\
            # make install && \\\n\
            # rm -rf /{soft}* /{soft}.tar.gz\n\n'
    #         ret = ret + f'RUN cd /usr/bin && wget https://ftp.isc.org/isc/bind9/{version}/{soft}.tar.gz || wget https://ftp.isc.org/isc/bind9/{version}/{soft}.tar.xz && \\\n\
    # if [ -f {soft}.tar.gz ]; then tar -xzvf {soft}.tar.gz; else tar -xJvf {soft}.tar.xz; fi && \\\n\
    # cd {soft} && \\\n\
    # ./configure --prefix=/usr/local/named --with-user=named --with-group=named --enable-threads && \\\n\
    # make && \\\n\
    # make install && \\\n\
    # rm -rf /{soft}* /{soft}.tar.gz /{soft}.tar.xz\n\n'


            ret = ret + f'RUN cd /usr/bin && wget https://ftp.isc.org/isc/bind9/{version}/{soft}.tar.gz || wget https://ftp.isc.org/isc/bind9/{version}/{soft}.tar.xz && \\\n\
    if [ -f {soft}.tar.gz ]; then tar -xzvf {soft}.tar.gz; else tar -xJvf {soft}.tar.xz; fi && \\\n\
    cd {soft} && \\\n\
    ./configure && \\\n\
    make && \\\n\
    make install && \\\n\
    rm -rf /{soft}* /{soft}.tar.gz /{soft}.tar.xz\n\n'
        
        elif re.match(bind10_pattern, soft):
            # TODO
            return 'bind10'
         # 添加缓存、日志目录并授予named用户权限
#         ret = ret + 'RUN mkdir -p /etc/bind /var/cache/bind /var/log/bind \n\
# RUN chown -R named:named /etc/bind /var/cache/bind /var/log/bind\n\n'

        # Avoid the "named: error while loading shared libraries: libisc" error when running named
        
        ret = ret + 'ENV LD_LIBRARY_PATH=/usr/local/lib/:$LD_LIBRARY_PATH\n'

        # 创建配置文件，其位置和apt-get安装的BIND相同
        ret = ret + 'RUN mkdir -p /etc/bind /var/cache/bind /var/log/bind \n'
        ret = ret + 'RUN touch /etc/bind/named.conf\n'
        ret = ret + 'RUN echo "include \\"/etc/bind/named.conf.options\\";" >> /etc/bind/named.conf\n'
        ret = ret + 'RUN echo "include \\"/etc/bind/named.conf.local\\";" >> /etc/bind/named.conf\n'
        ret = ret + 'RUN echo "include \\"/etc/bind/named.conf.default-zones\\";" >> /etc/bind/named.conf\n'
        ret = ret + 'RUN touch /etc/bind/named.conf.default-zones\n'
         # 添加内容到 named.conf.default-zones
        ret = ret + 'RUN echo "// prime the server with knowledge of the root servers" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "zone \\".\\" {" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    type hint;" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    file \\"/usr/share/dns/root.hints\\";" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "};" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "// be authoritative for the localhost forward and reverse zones, and for broadcast zones as per RFC 1912" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "zone \\"localhost\\" {" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    type master;" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    file \\"/etc/bind/db.local\\";" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "};" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "zone \\"127.in-addr.arpa\\" {" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    type master;" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    file \\"/etc/bind/db.127\\";" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "};" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "zone \\"0.in-addr.arpa\\" {" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    type master;" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    file \\"/etc/bind/db.0\\";" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "};" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "zone \\"255.in-addr.arpa\\" {" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    type master;" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "    file \\"/etc/bind/db.255\\";" >> /etc/bind/named.conf.default-zones\n'
        ret = ret + 'RUN echo "};" >> /etc/bind/named.conf.default-zones\n'
            
        # ret = ret + 'RUN touch /usr/local/etc/named.conf\n'

        return ret

    def _compileNode(self, node: Node) -> str:
        """!
        @brief Compile a single node. Will create folder for node and the
        dockerfile.

        @param node node to compile.

        @returns docker-compose service string.
        """
        (scope, type, _) = node.getRegistryInfo()
        prefix = self._contextToPrefix(scope, type)
        real_nodename = '{}{}'.format(prefix, node.getName())
        node_nets = ''
        dummy_addr_map = ''

        for iface in node.getInterfaces():
            net = iface.getNet()
            (netscope, _, _) = net.getRegistryInfo()
            net_prefix = self._contextToPrefix(netscope, 'net')
            if net.getType() == NetworkType.Bridge: net_prefix = ''
            real_netname = '{}{}'.format(net_prefix, net.getName())
            address = iface.getAddress()

            if self.__self_managed_network and net.getType() != NetworkType.Bridge:
                d_index: int = net.getAttribute('dummy_prefix_index')
                d_prefix: IPv4Network = net.getAttribute('dummy_prefix')
                d_address: IPv4Address = d_prefix[d_index]

                net.setAttribute('dummy_prefix_index', d_index + 1)

                dummy_addr_map += '{}/{},{}/{}\n'.format(
                    d_address, d_prefix.prefixlen,
                    iface.getAddress(), iface.getNet().getPrefix().prefixlen
                )

                address = d_address

                self._log('using self-managed network: using dummy address {}/{} for {}/{} on as{}/{}'.format(
                    d_address, d_prefix.prefixlen, iface.getAddress(), iface.getNet().getPrefix().prefixlen,
                    node.getAsn(), node.getName()
                ))

            if address == None:
                address = ""
            else:
                address = DockerCompilerFileTemplates['compose_service_network_address'].format(address = address)

            node_nets += DockerCompilerFileTemplates['compose_service_network'].format(
                netId = real_netname,
                address = address
            )

        _ports = node.getPorts()
        ports = ''
        if len(_ports) > 0:
            lst = ''
            for (h, n, p) in _ports:
                lst += DockerCompilerFileTemplates['compose_port'].format(
                    hostPort = h,
                    nodePort = n,
                    proto = p
                )
            ports = DockerCompilerFileTemplates['compose_ports'].format(
                portList = lst
            )

        _volumes = node.getSharedFolders()
        storages = node.getPersistentStorages()

        volumes = ''

        if len(_volumes) > 0 or len(storages) > 0:
            lst = ''

            for (nodePath, hostPath) in _volumes.items():
                lst += DockerCompilerFileTemplates['compose_volume'].format(
                    hostPath = hostPath,
                    nodePath = nodePath
                )

            for path in storages:
                lst += DockerCompilerFileTemplates['compose_storage'].format(
                    nodePath = path
                )

            volumes = DockerCompilerFileTemplates['compose_volumes'].format(
                volumeList = lst
            )

        dockerfile = DockerCompilerFileTemplates['dockerfile']
        mkdir(real_nodename)
        chdir(real_nodename)

        (image, soft) = self._selectImageFor(node)

        # 实现具体的Dockerfile中的安装命令
        # TODO 实现安装特定版本bind

        # __soft_install_tiers
        if not node.hasAttribute('__soft_install_tiers') and len(soft) > 0:
            dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends {}\n'.format(' '.join(sorted(soft)))

        if node.hasAttribute('__soft_install_tiers'):
            softLists: List[List[str]] = node.getAttribute('__soft_install_tiers')
            for softList in softLists:
                softList = set(softList) & soft
                if len(softList) == 0: continue
                for softItem in sorted(softList):
                    if any(re.match(enum_member.value, softItem) for enum_member in SpecificVersionSoftwareEnum):
                        dockerfile += self._compileSpecificVersionSoftwareForDocker(softItem)
                    else:
                        dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends {}\n'.format(softItem)
                # dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends {}\n'.format(' '.join(sorted(softList)))



        #included in the seedemu-base dockerImage.
        #dockerfile += 'RUN curl -L https://grml.org/zsh/zshrc > /root/.zshrc\n'
        dockerfile = 'FROM {}\n'.format(md5(image.getName().encode('utf-8')).hexdigest()) + dockerfile
        self._used_images.add(image.getName())

        for cmd in node.getBuildCommands(): dockerfile += 'RUN {}\n'.format(cmd)

        start_commands = ''

        if self.__self_managed_network:
            start_commands += 'chmod +x /replace_address.sh\n'
            start_commands += '/replace_address.sh\n'
            dockerfile += self._addFile('/replace_address.sh', DockerCompilerFileTemplates['replace_address_script'])
            dockerfile += self._addFile('/dummy_addr_map.txt', dummy_addr_map)
            dockerfile += self._addFile('/root/.zshrc.pre', DockerCompilerFileTemplates['zshrc_pre'])

        for (cmd, fork) in node.getStartCommands():
            start_commands += '{}{}\n'.format(cmd, ' &' if fork else '')

        for (cmd, fork) in node.getPostConfigCommands():
            start_commands += '{}{}\n'.format(cmd, ' &' if fork else '')

        dockerfile += self._addFile('/start.sh', DockerCompilerFileTemplates['start_script'].format(
            startCommands = start_commands
        ))

        dockerfile += self._addFile('/seedemu_sniffer', DockerCompilerFileTemplates['seedemu_sniffer'])
        dockerfile += self._addFile('/seedemu_worker', DockerCompilerFileTemplates['seedemu_worker'])

        dockerfile += 'RUN chmod +x /start.sh\n'
        dockerfile += 'RUN chmod +x /seedemu_sniffer\n'
        dockerfile += 'RUN chmod +x /seedemu_worker\n'

        for file in node.getFiles():
            (path, content) = file.get()
            dockerfile += self._addFile(path, content)

        for (cpath, hpath) in node.getImportedFiles().items():
            dockerfile += self._importFile(cpath, hpath)

        dockerfile += 'CMD ["/start.sh"]\n'
        print(dockerfile, file=open('Dockerfile', 'w'))

        chdir('..')

        name = self.__naming_scheme.format(
            asn = node.getAsn(),
            role = self._nodeRoleToString(node.getRole()),
            name = node.getName(),
            displayName = node.getDisplayName() if node.getDisplayName() != None else node.getName(),
            primaryIp = node.getInterfaces()[0].getAddress()
        )

        name = sub(r'[^a-zA-Z0-9_.-]', '_', name)

        return DockerCompilerFileTemplates['compose_service'].format(
            nodeId = real_nodename,
            nodeName = name,
            dependsOn = md5(image.getName().encode('utf-8')).hexdigest(),
            networks = node_nets,
            # privileged = 'true' if node.isPrivileged() else 'false',
            ports = ports,
            labelList = self._getNodeMeta(node),
            volumes = volumes
        )

    def _compileNet(self, net: Network) -> str:
        """!
        @brief compile a network.

        @param net net object.

        @returns docker-compose network string.
        """
        (scope, _, _) = net.getRegistryInfo()
        if self.__self_managed_network and net.getType() != NetworkType.Bridge:
            pfx = next(self.__dummy_network_pool)
            net.setAttribute('dummy_prefix', pfx)
            net.setAttribute('dummy_prefix_index', 2)
            self._log('self-managed network: using dummy prefix {}'.format(pfx))

        net_prefix = self._contextToPrefix(scope, 'net')
        if net.getType() == NetworkType.Bridge: net_prefix = ''

        return DockerCompilerFileTemplates['compose_network'].format(
            netId = '{}{}'.format(net_prefix, net.getName()),
            prefix = net.getAttribute('dummy_prefix') if self.__self_managed_network and net.getType() != NetworkType.Bridge else net.getPrefix(),
            mtu = net.getMtu(),
            labelList = self._getNetMeta(net)
        )

    def _makeDummies(self) -> str:
        """!
        @brief create dummy services to get around docker pull limits.

        @returns docker-compose service string.
        """
        mkdir('dummies')
        chdir('dummies')

        dummies = ''

        for image in self._used_images:
            self._log('adding dummy service for image {}...'.format(image))

            imageDigest = md5(image.encode('utf-8')).hexdigest()
            dockerImage, _ = self.__images[image]
            if dockerImage.isLocal():
                dummies += DockerCompilerFileTemplates['compose_dummy'].format(
                    imageDigest = imageDigest,
                    dependsOn= DockerCompilerFileTemplates['depends_on'].format(
                        dependsOn = image
                    )
                )
            else:
                dummies += DockerCompilerFileTemplates['compose_dummy'].format(
                    imageDigest = imageDigest,
                    dependsOn= ""
                )

            dockerfile = 'FROM {}\n'.format(image)
            print(dockerfile, file=open(imageDigest, 'w'))

        chdir('..')

        return dummies

    def _doCompile(self, emulator: Emulator):
        registry = emulator.getRegistry()

        self._groupSoftware(emulator)

        for ((scope, type, name), obj) in registry.getAll().items():

            if type == 'net':
                self._log('creating network: {}/{}...'.format(scope, name))
                self.__networks += self._compileNet(obj)

        for ((scope, type, name), obj) in registry.getAll().items():
            if type == 'rnode':
                self._log('compiling router node {} for as{}...'.format(name, scope))
                self.__services += self._compileNode(obj)

            if type == 'csnode':
                self._log('compiling control service node {} for as{}...'.format(name, scope))
                self.__services += self._compileNode(obj)

            if type == 'hnode':
                self._log('compiling host node {} for as{}...'.format(name, scope))
                self.__services += self._compileNode(obj)

            if type == 'rs':
                self._log('compiling rs node for {}...'.format(name))
                self.__services += self._compileNode(obj)

            if type == 'snode':
                self._log('compiling service node {}...'.format(name))
                self.__services += self._compileNode(obj)

        if self.__internet_map_enabled:
            self._log('enabling seedemu-internet-map...')

            self.__services += DockerCompilerFileTemplates['seedemu_internet_map'].format(
                clientImage = SEEDEMU_INTERNET_MAP_IMAGE,
                clientPort = self.__internet_map_port
            )

        if self.__ether_view_enabled:
            self._log('enabling seedemu-ether-view...')

            self.__services += DockerCompilerFileTemplates['seedemu_ether_view'].format(
                clientImage = SEEDEMU_ETHER_VIEW_IMAGE,
                clientPort = self.__ether_view_port
            )

        local_images = ''

        for (image, _) in self.__images.values():
            if image.getName() not in self._used_images or not image.isLocal(): continue
            local_images += DockerCompilerFileTemplates['local_image'].format(
                imageName = image.getName(),
                dirName = image.getDirName()
            )

        self._log('creating docker-compose.yml...'.format(scope, name))
        print(DockerCompilerFileTemplates['compose'].format(
            services = self.__services,
            networks = self.__networks,
            dummies = local_images + self._makeDummies()
        ), file=open('docker-compose.yml', 'w'))
