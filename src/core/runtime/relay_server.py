from __future__ import annotations

import asyncio
import os
import socket
import sys
import traceback

from src.core.runtime.runtime_controller import RelayRuntimeController
from src.utils.packet_templates import ClientHelloMaker
from src.core.runtime import runtime_state


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
        from src.core.packet_injection.tcp_injector import FakeInjectiveConnection

        loop = asyncio.get_running_loop()

        if runtime_state.DATA_MODE == "tls":
            fake_data = ClientHelloMaker.get_client_hello_with(
                os.urandom(32),
                os.urandom(32),
                runtime_state.FAKE_SNI,
                os.urandom(32),
            )
        else:
            sys.exit("impossible mode!")
        outgoing_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        outgoing_sock.setblocking(False)
        outgoing_sock.bind((runtime_state.INTERFACE_IPV4, 0))
        outgoing_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        outgoing_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 11)
        outgoing_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 2)
        outgoing_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        src_port = outgoing_sock.getsockname()[1]
        fake_injective_conn = FakeInjectiveConnection(
            outgoing_sock,
            runtime_state.INTERFACE_IPV4,
            runtime_state.CONNECT_IP,
            src_port,
            runtime_state.CONNECT_PORT,
            fake_data,
            runtime_state.BYPASS_METHOD,
            incoming_sock,
        )
        runtime_state.fake_injective_connections[fake_injective_conn.id] = fake_injective_conn
        try:
            await loop.sock_connect(outgoing_sock, (runtime_state.CONNECT_IP, runtime_state.CONNECT_PORT))
        except Exception:
            fake_injective_conn.monitor = False
            del runtime_state.fake_injective_connections[fake_injective_conn.id]
            outgoing_sock.close()
            incoming_sock.close()
            return

        if runtime_state.BYPASS_METHOD == "wrong_seq":
            try:
                await asyncio.wait_for(fake_injective_conn.t2a_event.wait(), 2)
                if fake_injective_conn.t2a_msg == "unexpected_close":
                    raise ValueError("unexpected close")
                if fake_injective_conn.t2a_msg != "fake_data_ack_recv":
                    sys.exit("impossible t2a msg!")
            except Exception:
                fake_injective_conn.monitor = False
                del runtime_state.fake_injective_connections[fake_injective_conn.id]
                outgoing_sock.close()
                incoming_sock.close()
                return
        else:
            sys.exit("unknown bypass method!")

        fake_injective_conn.monitor = False
        del runtime_state.fake_injective_connections[fake_injective_conn.id]

        oti_task = asyncio.create_task(
            relay_main_loop(outgoing_sock, incoming_sock, asyncio.current_task(), b""))
        await relay_main_loop(incoming_sock, outgoing_sock, oti_task, b"")

    except Exception:
        traceback.print_exc()
        sys.exit("handle should not raise exception")


async def main():
    mother_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    mother_sock.setblocking(False)
    mother_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mother_sock.bind((runtime_state.LISTEN_HOST, runtime_state.LISTEN_PORT))
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
    controller = RelayRuntimeController(config_path=config_path, log_callback=log_line)
    try:
        xray_settings = controller.start()
        controller.start_packet_injector()
        log_line("SNI-Spoofing Relay started.")
        log_line(f"Connection mode: {controller.connection_mode}")
        log_line(
            f"Listening on {runtime_state.LISTEN_HOST}:{runtime_state.LISTEN_PORT}, forwarding to "
            f"{runtime_state.CONNECT_IP}:{runtime_state.CONNECT_PORT} with fake SNI="
            f"{runtime_state.FAKE_SNI.decode(errors='replace')}"
        )
        log_line()
        if xray_settings is not None:
            if xray_settings.uses_tun:
                log_line("Bundled Xray started. TUN inbound is active.")
            else:
                log_line(
                    f"Bundled Xray started. Mixed proxy: "
                    f"{xray_settings.mixed_host}:{xray_settings.mixed_port}"
                )
        asyncio.run(main())
    finally:
        controller.stop()
    return 0


__all__ = [
    "relay_main_loop",
    "handle",
    "main",
    "run_headless",
    "log_line",
]
