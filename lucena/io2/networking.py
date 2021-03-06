# -*- coding: utf-8 -*-
import random
from ctypes import *
from socket import AF_INET, AF_INET6, inet_ntop
from sys import platform

import zmq


try:
    from socket import AF_PACKET
except ImportError:
    AF_PACKET = -1


if platform.startswith("darwin") or platform.startswith("freebsd"):
    AF_LINK = 18
    IFT_ETHER = 0x6
else:
    AF_LINK = -1
    IFT_ETHER = -1


def create_pipe(ctx, hwm=1000):
    socket0 = zmq.Socket(ctx, zmq.PAIR)
    socket0.set_hwm(hwm)
    socket0.setsockopt(zmq.LINGER, 0)
    socket1 = zmq.Socket(ctx, zmq.PAIR)
    socket1.set_hwm(hwm)
    socket1.setsockopt(zmq.LINGER, 0)
    while True:
        try:
            endpoint = "inproc://$pipe-{}".format(random.randint(1, 9999999999))
            socket1.bind(endpoint)
        except zmq.ZMQError:
            continue
        else:
            break
    socket0.connect(endpoint)
    return socket1, socket0


def get_if_addresses():
    """
    Retrieve all relevant information of IPv4/IPv6 network interfaces.
    Based on http://pastebin.com/wxjai3Mw (Author unknown)
    """

    class ifa_ifu_u(Union):
        _fields_ = [
            ("ifu_broadaddr", c_void_p),
            ("ifu_dstaddr", c_void_p)
        ]

    class ifaddrs(Structure):
        _fields_ = [
            ("ifa_next", c_void_p),
            ("ifa_name", c_char_p),
            ("ifa_flags", c_uint),
            ("ifa_addr", c_void_p),
            ("ifa_netmask", c_void_p),
            ("ifa_ifu", ifa_ifu_u),
            ("ifa_data", c_void_p)
        ]

    # AF_UNKNOWN / generic
    if platform.startswith("darwin") or platform.startswith("freebsd"):
        class sockaddr(Structure):
            _fields_ = [
                ("sa_len", c_uint8),
                ("sa_family", c_uint8),
                ("sa_data", (c_uint8 * 14))
            ]
    else:
        class sockaddr(Structure):
            _fields_ = [
                ("sa_family", c_uint16),
                ("sa_data", (c_uint8 * 14))
            ]

    # AF_INET / IPv4
    class in_addr(Union):
        _fields_ = [
            ("s_addr", c_uint32),
        ]

    if platform.startswith("darwin") or platform.startswith("freebsd"):
        class sockaddr_in(Structure):
            _fields_ = [
                ("sin_len", c_uint8),
                ("sin_family", c_uint8),
                ("sin_port", c_ushort),
                ("sin_addr", in_addr),
                ("sin_zero", (c_char * 8))  # padding
            ]
    else:
        class sockaddr_in(Structure):
            _fields_ = [
                ("sin_family", c_short),
                ("sin_port", c_ushort),
                ("sin_addr", in_addr),
                ("sin_zero",  (c_char * 8))  # padding
            ]

    # AF_INET6 / IPv6
    class in6_u(Union):
        _fields_ = [
            ("u6_addr8", (c_uint8 * 16)),
            ("u6_addr16", (c_uint16 * 8)),
            ("u6_addr32", (c_uint32 * 4))
        ]

    class in6_addr(Union):
        _fields_ = [
            ("in6_u", in6_u),
        ]

    if platform.startswith("darwin") or platform.startswith("freebsd"):
        class sockaddr_in6(Structure):
            _fields_ = [
                ("sin6_len", c_uint8),
                ("sin6_family", c_uint8),
                ("sin6_port", c_ushort),
                ("sin6_flowinfo", c_uint32),
                ("sin6_addr", in6_addr),
                ("sin6_scope_id", c_uint32),
            ]
    else:
        class sockaddr_in6(Structure):
            _fields_ = [
                ("sin6_family", c_short),
                ("sin6_port", c_ushort),
                ("sin6_flowinfo", c_uint32),
                ("sin6_addr", in6_addr),
                ("sin6_scope_id", c_uint32),
            ]

    # AF_PACKET / Linux
    class sockaddr_ll(Structure):
        _fields_ = [
            ("sll_family", c_uint16),
            ("sll_protocol", c_uint16),
            ("sll_ifindex", c_uint32),
            ("sll_hatype", c_uint16),
            ("sll_pktype", c_uint8),
            ("sll_halen", c_uint8),
            ("sll_addr", (c_uint8 * 8))
        ]

    # AF_LINK / BSD|OSX
    class sockaddr_dl(Structure):
        _fields_ = [
            ("sdl_len", c_uint8),
            ("sdl_family", c_uint8),
            ("sdl_index", c_uint16),
            ("sdl_type", c_uint8),
            ("sdl_nlen", c_uint8),
            ("sdl_alen", c_uint8),
            ("sdl_slen", c_uint8),
            ("sdl_data", (c_uint8 * 46))
        ]

    if platform.startswith("darwin"):
        libc = CDLL("libSystem.dylib")

    elif platform.startswith("freebsd"):
        libc = CDLL("libc.so")

    else:
        libc = CDLL("libc.so.6")

    ptr = c_void_p(None)
    result = libc.getifaddrs(pointer(ptr))
    if result:
        return None
    ifa = ifaddrs.from_address(ptr.value)
    result = []

    while ifa:
        # Python 2 gives us a string, Python 3 an array of bytes
        if type(ifa.ifa_name) is str:
            name = ifa.ifa_name
        else:
            name = ifa.ifa_name.decode()

        if ifa.ifa_addr:
            sa = sockaddr.from_address(ifa.ifa_addr)

            data = {}

            if sa.sa_family == AF_INET:
                if ifa.ifa_addr is not None:
                    si = sockaddr_in.from_address(ifa.ifa_addr)
                    data['addr'] = inet_ntop(AF_INET, si.sin_addr)
                if ifa.ifa_netmask is not None:
                    si = sockaddr_in.from_address(ifa.ifa_netmask)
                    data['netmask'] = inet_ntop(AF_INET, si.sin_addr)

                # check if a valid broadcast address is set and retrieve it
                # 0x2 == IFF_BROADCAST
                if ifa.ifa_flags & 0x2:
                    si = sockaddr_in.from_address(ifa.ifa_ifu.ifu_broadaddr)
                    data['broadcast'] = inet_ntop(AF_INET, si.sin_addr)

            if sa.sa_family == AF_INET6:
                if ifa.ifa_addr is not None:
                    si = sockaddr_in6.from_address(ifa.ifa_addr)
                    data['addr'] = inet_ntop(AF_INET6, si.sin6_addr)

                    if data['addr'].startswith('fe80:'):
                        data['scope'] = si.sin6_scope_id

                if ifa.ifa_netmask is not None:
                    si = sockaddr_in6.from_address(ifa.ifa_netmask)
                    data['netmask'] = inet_ntop(AF_INET6, si.sin6_addr)

            if sa.sa_family == AF_PACKET:
                if ifa.ifa_addr is not None:
                    si = sockaddr_ll.from_address(ifa.ifa_addr)
                    addr = ""
                    total = 0
                    for i in range(si.sll_halen):
                        total += si.sll_addr[i]
                        addr += "%02x:" % si.sll_addr[i]
                    addr = addr[:-1]
                    if total > 0:
                        data['addr'] = addr

            if sa.sa_family == AF_LINK:
                dl = sockaddr_dl.from_address(ifa.ifa_addr)

                if dl.sdl_type == IFT_ETHER:
                    addr = ""
                    for i in range(dl.sdl_alen):
                        addr += "%02x:" % dl.sdl_data[dl.sdl_nlen + i]

                    addr = addr[:-1]
                    data['addr'] = addr

            if len(data) > 0:
                iface = {}
                for interface in result:
                    if name in interface.keys():
                        iface = interface
                        break
                if iface:
                    iface[name][sa.sa_family] = data
                else:
                    iface[name] = { sa.sa_family : data }
                    result.append(iface)

        if ifa.ifa_next:
            ifa = ifaddrs.from_address(ifa.ifa_next)
        else:
            break

    libc.freeifaddrs(ptr)
    return result
