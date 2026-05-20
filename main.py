import argparse
import atexit
import asyncio
import os
import socket
import sys
import traceback
import threading

# from utils.proxy_protocols import parse_vless_protocol
from app_config import get_app_dir, get_config_port, get_config_string, load_config
from utils.network_tools import get_default_interface_ipv4
from utils.packet_templates import ClientHelloMaker
from utils.xray import XrayLocalProxySettings, XrayProcessManager, build_xray_config, parse_xray_share_url
from fake_tcp import FakeInjectiveConnection, FakeTcpInjector


config: dict[str, object] = {}
CONFIG_PATH_OVERRIDE: str | None = None
LISTEN_HOST = ""
LISTEN_PORT = 0
FAKE_SNI = b""
CONNECT_IP = ""
CONNECT_PORT = 0
INTERFACE_IPV4 = ""
DATA_MODE = "tls"
BYPASS_METHOD = "wrong_seq"

##################

fake_injective_connections: dict[tuple, FakeInjectiveConnection] = {}


def resolve_connect_port(config_data: dict[str, object]) -> int:
    share_url = get_config_string(config_data, "XRAY_URL", "").strip()
    if not share_url:
        share_url = get_config_string(config_data, "VLESS_URL", "").strip()
    if share_url:
        return parse_xray_share_url(share_url).port
    return get_config_port(config_data, "CONNECT_PORT", 443)


def load_runtime_settings(config_path: str | None = None) -> None:
    global config, LISTEN_HOST, LISTEN_PORT, FAKE_SNI, CONNECT_IP, CONNECT_PORT, INTERFACE_IPV4

    config = load_config(config_path or CONFIG_PATH_OVERRIDE)
    LISTEN_HOST = get_config_string(config, "LISTEN_HOST", "0.0.0.0")
    LISTEN_PORT = get_config_port(config, "LISTEN_PORT", 40443)

    connect_ip = get_config_string(config, "CONNECT_IP").strip()
    if not connect_ip:
        raise ValueError("CONNECT_IP must not be empty")

    fake_sni = get_config_string(config, "FAKE_SNI").strip()
    if not fake_sni:
        raise ValueError("FAKE_SNI must not be empty")

    CONNECT_IP = connect_ip
    CONNECT_PORT = resolve_connect_port(config)
    FAKE_SNI = fake_sni.encode()
    INTERFACE_IPV4 = get_default_interface_ipv4(CONNECT_IP)
    if not INTERFACE_IPV4:
        raise ValueError(f"Could not determine a local IPv4 route for CONNECT_IP={CONNECT_IP}")


def ensure_runtime_settings_loaded() -> None:
    if config:
        return
    load_runtime_settings(CONFIG_PATH_OVERRIDE)


def resolve_runtime_path(relative_or_absolute_path: str) -> str:
    if os.path.isabs(relative_or_absolute_path):
        return relative_or_absolute_path
    return os.path.normpath(os.path.join(get_app_dir(), relative_or_absolute_path))


def get_xray_relay_host() -> str:
    explicit_relay_host = get_config_string(config, "XRAY_RELAY_HOST", "").strip()
    if explicit_relay_host:
        return explicit_relay_host
    if LISTEN_HOST == "0.0.0.0":
        return "127.0.0.1"
    if LISTEN_HOST == "::":
        return "::1"
    return LISTEN_HOST


def build_xray_manager() -> tuple[XrayProcessManager | None, XrayLocalProxySettings | None]:
    ensure_runtime_settings_loaded()
    share_url = get_config_string(config, "XRAY_URL", "").strip()
    if not share_url:
        share_url = get_config_string(config, "VLESS_URL", "").strip()
    if not share_url:
        return None, None

    xray_settings = XrayLocalProxySettings(
        binary_path=resolve_runtime_path(get_config_string(config, "XRAY_BINARY_PATH", os.path.join("xray", "xray.exe"))),
        socks_host="127.0.0.1",
        socks_port=get_config_port(config, "XRAY_SOCKS_PORT", 10808),
        http_host="127.0.0.1",
        http_port=get_config_port(config, "XRAY_HTTP_PORT", 10809),
        log_level=get_config_string(config, "XRAY_LOG_LEVEL", "warning"),
    )
    if xray_settings.socks_port == xray_settings.http_port:
        raise ValueError("XRAY_SOCKS_PORT and XRAY_HTTP_PORT must be different")
    if LISTEN_PORT in {xray_settings.socks_port, xray_settings.http_port}:
        raise ValueError("LISTEN_PORT must be different from XRAY_SOCKS_PORT and XRAY_HTTP_PORT")

    share_profile = parse_xray_share_url(share_url)
    relay_host = get_xray_relay_host()
    xray_config = build_xray_config(share_profile, xray_settings, relay_host, LISTEN_PORT)
    return XrayProcessManager(xray_settings.binary_path, xray_config), xray_settings


def maybe_start_xray_proxy() -> tuple[XrayProcessManager | None, XrayLocalProxySettings | None]:
    load_runtime_settings(CONFIG_PATH_OVERRIDE)
    xray_manager, xray_settings = build_xray_manager()
    if xray_manager is None:
        return None, None
    xray_manager.start()
    return xray_manager, xray_settings


def stop_xray_proxy(xray_manager: XrayProcessManager | None) -> None:
    if xray_manager is None:
        return
    xray_manager.stop()


async def relay_main_loop(sock_1: socket.socket, sock_2: socket.socket, peer_task: asyncio.Task,
                          first_prefix_data: bytes):
    try:
        loop = asyncio.get_running_loop()
        while True:
            try:
                data = await loop.sock_recv(sock_1, 65575)
                if not data:
                    raise ValueError("eof")
                if first_prefix_data:
                    data = first_prefix_data + data
                    first_prefix_data = b""
                await loop.sock_sendall(sock_2, data)
            except Exception:
                sock_1.close()
                sock_2.close()
                peer_task.cancel()
                return
    except Exception:
        traceback.print_exc()
        sys.exit("relay main loop error!")


async def handle(incoming_sock: socket.socket, incoming_remote_addr):
    try:
        loop = asyncio.get_running_loop()
        # try:
        #     data = await loop.sock_recv(incoming_sock, 65575)
        #     if not data:
        #         raise ValueError("eof")
        # except Exception:
        #     incoming_sock.close()
        #     return
        # try:
        #     version, uuid_bytes, transport_protocol, remote_address_type, remote_address, remote_port, payload_index = parse_vless_protocol(
        #         data)
        # except Exception as e:
        #     print("No Vless Request!, Connection Closed", repr(e), data)
        #     incoming_sock.close()
        #     return
        # if transport_protocol != "tcp":
        #     print("Transport Protocol Error!, Connection Closed", transport_protocol, data)
        #     incoming_sock.close()
        #     return
        # if remote_address_type == "hostname":
        #     print("hostname address not implemented yet!", data)
        #     incoming_sock.close()
        #     return
        # if remote_address_type == "ipv4":
        #     if not INTERFACE_IPV4:
        #         print("no interface ipv4!", data)
        #         incoming_sock.close()
        #         return
        #     family = socket.AF_INET
        #     src_ip = INTERFACE_IPV4
        #
        # elif remote_address_type == "ipv6":
        #     if not INTERFACE_IPV6:
        #         print("no interface ipv6!", data)
        #         incoming_sock.close()
        #         return
        #     family = socket.AF_INET6
        #     src_ip = INTERFACE_IPV6
        #
        # else:
        #     print(data)
        #     sys.exit("impossible address type!")

        # try:
        #     fake_sni_host, data_mode, bypass_method = UUID_FAKE_MAP[uuid_bytes]
        # except KeyError:
        #     print("unmatched uuid", uuid_bytes)
        #     incoming_sock.close()
        #     return

        # if data_mode == "http":
        #     ...
        if DATA_MODE == "tls":
            fake_data = ClientHelloMaker.get_client_hello_with(os.urandom(32), os.urandom(32), FAKE_SNI,
                                                               os.urandom(32))
        else:
            sys.exit("impossible mode!")
        outgoing_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        outgoing_sock.setblocking(False)
        outgoing_sock.bind((INTERFACE_IPV4, 0))
        outgoing_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        outgoing_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 11)
        outgoing_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 2)
        outgoing_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        src_port = outgoing_sock.getsockname()[1]
        fake_injective_conn = FakeInjectiveConnection(outgoing_sock, INTERFACE_IPV4, CONNECT_IP, src_port, CONNECT_PORT,
                                                      fake_data,
                                                      BYPASS_METHOD, incoming_sock)
        fake_injective_connections[fake_injective_conn.id] = fake_injective_conn
        try:
            await loop.sock_connect(outgoing_sock, (CONNECT_IP, CONNECT_PORT))
        except Exception:
            fake_injective_conn.monitor = False
            del fake_injective_connections[fake_injective_conn.id]
            outgoing_sock.close()
            incoming_sock.close()
            return

        # if bypass_method == "wrong_checksum":
        #     ...

        if BYPASS_METHOD == "wrong_seq":
            try:
                await asyncio.wait_for(fake_injective_conn.t2a_event.wait(), 2)
                if fake_injective_conn.t2a_msg == "unexpected_close":
                    raise ValueError("unexpected close")
                if fake_injective_conn.t2a_msg == "fake_data_ack_recv":
                    pass
                else:
                    sys.exit("impossible t2a msg!")
            except Exception:
                fake_injective_conn.monitor = False
                del fake_injective_connections[fake_injective_conn.id]
                outgoing_sock.close()
                incoming_sock.close()
                return
        else:
            sys.exit("unknown bypass method!")

        fake_injective_conn.monitor = False
        del fake_injective_connections[fake_injective_conn.id]

        # early_data = data[payload_index:]
        # if early_data:
        #     try:
        #         sent_len = await loop.sock_sendall(outgoing_sock, early_data)
        #         if sent_len != len(early_data):
        #             raise ValueError("incomplete send")
        #     except Exception:
        #         outgoing_sock.close()
        #         incoming_sock.close()
        #         return

        oti_task = asyncio.create_task(
            relay_main_loop(outgoing_sock, incoming_sock, asyncio.current_task(), b""))  # bytes([version, 0])
        await relay_main_loop(incoming_sock, outgoing_sock, oti_task, b"")



    except Exception:
        traceback.print_exc()
        sys.exit("handle should not raise exception")


async def main():
    mother_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    mother_sock.setblocking(False)
    mother_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mother_sock.bind((LISTEN_HOST, LISTEN_PORT))
    mother_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    mother_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 11)
    mother_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 2)
    mother_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    mother_sock.listen()
    loop = asyncio.get_running_loop()
    while True:
        incoming_sock, addr = await loop.sock_accept(mother_sock)
        incoming_sock.setblocking(False)
        incoming_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        incoming_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 11)
        incoming_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 2)
        incoming_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        asyncio.create_task(handle(incoming_sock, addr))


def log_line(message: str = "") -> None:
    stdout = sys.stdout
    line = f"{message}\n"

    if hasattr(stdout, "buffer") and not stdout.isatty():
        stdout.buffer.write(line.encode("utf-8"))
        stdout.flush()
        return

    try:
        stdout.write(line)
        stdout.flush()
        return
    except UnicodeEncodeError:
        pass

    if not hasattr(stdout, "buffer"):
        stdout.write(message.encode("ascii", errors="backslashreplace").decode("ascii") + "\n")
        stdout.flush()
        return

    encoding = stdout.encoding or "utf-8"
    stdout.buffer.write(line.encode(encoding, errors="backslashreplace"))
    stdout.flush()


def run_headless(config_path: str | None = None) -> int:
    load_runtime_settings(config_path)
    xray_manager: XrayProcessManager | None = None
    try:
        xray_manager, xray_settings = maybe_start_xray_proxy()
        if xray_manager is not None:
            atexit.register(stop_xray_proxy, xray_manager)

        w_filter = "tcp and " + "(" + "(ip.SrcAddr == " + INTERFACE_IPV4 + " and ip.DstAddr == " + CONNECT_IP + ")" + " or " + "(ip.SrcAddr == " + CONNECT_IP + " and ip.DstAddr == " + INTERFACE_IPV4 + ")" + ")"
        fake_tcp_injector = FakeTcpInjector(w_filter, fake_injective_connections)
        threading.Thread(target=fake_tcp_injector.run, args=(), daemon=True).start()
        log_line("SNI-Spoofing Relay started.")
        log_line(f"Listening on {LISTEN_HOST}:{LISTEN_PORT}, forwarding to {CONNECT_IP}:{CONNECT_PORT} with fake SNI={FAKE_SNI.decode(errors='replace')}")
        log_line()
        if xray_settings is not None:
            log_line(f"Bundled Xray started. SOCKS5 proxy: {xray_settings.socks_host}:{xray_settings.socks_port}")
            log_line(f"Bundled Xray started. HTTP proxy: {xray_settings.http_host}:{xray_settings.http_port}")
        asyncio.run(main())
    finally:
        stop_xray_proxy(xray_manager)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SNI-Spoofing relay and control panel.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the relay without launching the control panel.",
    )
    parser.add_argument(
        "--config",
        help="Optional path to an alternate config.json file.",
    )
    return parser.parse_args()


def cli_main() -> int:
    global CONFIG_PATH_OVERRIDE

    args = parse_args()
    CONFIG_PATH_OVERRIDE = args.config
    if args.headless:
        return run_headless(args.config)

    from gui import launch_gui

    launch_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
