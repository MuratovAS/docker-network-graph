#!/usr/bin/python3

import os
import argparse
import random
import docker
import typing
import urllib.parse
from dataclasses import dataclass
from graphviz import Graph
from graphviz import FORMATS

# colorlover.scales["12"]["qual"]["Paired"] converted to hex strings
# Also some neutral colors from colormind.io
COLORS = [
    "#1f78b4",
    "#33a02c",
    "#e31a1c",
    "#ff7f00",
    "#6a3d9a",
    "#b15928",
    "#a6cee3",
    "#b2df8a",
    "#fdbf6f",
    "#cab2d6",
    "#90f530",
    "#0d8bad",
    "#e98420",
    "#0e9997",
    "#6a5164",
    "#afa277",
    "#149ead",
    "#a54a56",
]
i = 0


@dataclass
class Network:
    name: str
    gateway: str
    internal: bool
    isolated: bool
    color: str


@dataclass
class Interface:
    endpoint_id: str
    address: str
    aliases: typing.List[str]

@dataclass
class Port:
    port: str
    
@dataclass
class Container:
    container_id: str
    name: str
    interfaces: typing.List[Interface]
    ports: typing.List[Interface]


@dataclass
class Link:
    container_id: str
    endpoint_id: str
    network_name: str


def get_unique_color() -> str:
    global i

    if i < len(COLORS):
        c = COLORS[i]
        i += 1
    else:
        # Generate random color if we've already used the 12 preset ones
        c = '#'.join([f"{random.randint(0, 255):02x}" for _ in range(3)])

    return c


def get_networks(
    client: docker.DockerClient, verbose: bool
) -> typing.Dict[str, Network]:
    networks: typing.Dict[str, Network] = {}

    for net in sorted(client.networks.list(), key=lambda k: k.name):
        try:
            gateway = net.attrs["IPAM"]["Config"][0]["Subnet"]
        except (KeyError, IndexError, TypeError):
            # This network doesn't seem to be used, skip it
            continue

        internal = False
        try:
            if net.attrs["Internal"]:
                internal = True
        except KeyError:
            pass

        isolated = False
        try:
            if net.attrs["Options"]["com.docker.network.bridge.enable_icc"] == "false":
                isolated = True
        except KeyError:
            pass

        if verbose:
            print(
                f"Network: {net.name} {'internal' if internal else ''} {'isolated' if isolated else ''} gw:{gateway}"
            )

        color = get_unique_color()
        networks[net.name] = Network(net.name, gateway, internal, isolated, color)

    networks["host"] = Network("host", "0.0.0.0", False, False, "#808080")

    return networks


def get_containers(
    client: docker.DockerClient, verbose: bool
) -> (typing.List[Container], typing.List[Link]):
    containers: typing.List[Container] = []
    links: typing.List[Link] = []

    for container in client.containers.list():
        interfaces: typing.List[Interface] = []
        ports: typing.List[Port] = []

        for port_name, port_info in container.attrs["NetworkSettings"]["Ports"].items():
            ports.append(Port(port_name))

        # Iterate over container interfaces
        for net_name, net_info in container.attrs["NetworkSettings"]["Networks"].items():
            endpoint_id = net_info["EndpointID"]

            aliases = []
            if net_info["Aliases"]:
                for alias in net_info["Aliases"]:
                    # The aliases always contain the shortened container id and container name
                    if alias != container.id[:12] and alias != container.name:
                        aliases.append(alias)

            interfaces.append(Interface(endpoint_id, net_info["IPAddress"], aliases))
            links.append(Link(container.id, endpoint_id, net_name))

        if verbose:
            print(f"Container: {container.name} {ports} {''.join([iface.address for iface in interfaces])}")

        containers.append(Container(container.id, container.name, interfaces, ports))

    return containers, links


def draw_network(g: Graph, net: Network):
    # <gw_iface> {net.gateway} | 
    label = f"{{{net.name}"
    if net.internal:
        label += " | Internal"
    if net.isolated:
        label += " | Containers isolated"
    label += "}"

    g.node(
        f"network_{net.name}",
        shape="record",
        label=label,
        color=net.color + "60",
        style="filled,rounded",
    )


def draw_container(g: Graph, c: Container):
    iface_labels = []
    port_labels = []
    
    for iport in c.ports:
        port_label = "{"
        port_label += f"{iport.port} }}"
        port_labels.append(port_label)

    for iface in c.interfaces:
        iface_label = "{"

        for alias in iface.aliases:
            iface_label += f" {alias} |"

        iface_label += f"<{iface.endpoint_id}> {iface.address} }}"
        iface_labels.append(iface_label)
    
    label =f"{{ {c.name} "
    if port_labels:
        label = label + f"| {{ {' | '.join(port_labels)} }} "
    label = label + f"| {{ {' | '.join(iface_labels)} }} }}"

    g.node(
        f"container_{c.container_id}",
        shape="record",
        label=label,
        fillcolor="#cdcdcd",
        style="filled",
    )


def draw_link(g: Graph, networks: typing.Dict[str, Network], link: Link):
    if networks[link.network_name].isolated:
        style="dashed"
    elif  networks[link.network_name].name == "host":
        style="bold"
    else:
        style="solid"
        
    g.edge(
        f"container_{link.container_id}:{link.endpoint_id}",
        f"network_{link.network_name}",
        color=networks[link.network_name].color,
        style=style,
    )


def generate_graph(verbose: bool, file: str, url: str):
    docker_client = docker.from_env()

    networks = get_networks(docker_client, verbose)
    containers, links = get_containers(docker_client, verbose)

    if file:
        base, ext = os.path.splitext(file)
        g = Graph(
            comment="Docker Network Graph",
            engine="sfdp",
            format=ext[1:],
            graph_attr=dict(splines="true", rankdir="LR", bgcolor="transparent"),
        )
    else:
        g = Graph(
            comment="Docker Network Graph",
            engine="sfdp",
            graph_attr=dict(splines="true", rankdir="LR", bgcolor="transparent"),
        )

    for _, network in networks.items():
        draw_network(g, network)

    for container in containers:
        draw_container(g, container)

    for link in links:
        if link.network_name != "none":
            draw_link(g, networks, link)

    for _, network in networks.items():
        if network.internal != True:
            if network.name != "host":
                g.edge(
                    f"network_{network.name}",
                    f"network_host",
                    color="#808080",
                    style="dotted",
                )
            
    if file:
        g.render(base)
    else:
        if url:
            print("https://dreampuf.github.io/GraphvizOnline/#" + urllib.parse.quote(g.source))
        else:
            print(g.source)


def graphviz_output_file(filename: str):
    ext = os.path.splitext(filename)[1][1:]
    if ext.lower() not in FORMATS:
        raise argparse.ArgumentTypeError("Must be valid graphviz output format")
    return filename

    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize docker networks.")
    parser.add_argument("-v", "--verbose", help="verbose output", action="store_true")
    parser.add_argument("-o", "--out", help="write output to file", type=graphviz_output_file)
    parser.add_argument("-u", "--url", help="generate link for GraphvizOnline", action="store_true")
    args = parser.parse_args()

    generate_graph(args.verbose, args.out, args.url)