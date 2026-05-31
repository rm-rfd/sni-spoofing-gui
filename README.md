<img width="1280" height="869" alt="image" src="https://github.com/user-attachments/assets/1432ffe0-9047-4fc3-a287-d85d8ea42de2" />
# RM SNI Spoofer

This project is built on top of the work by Patterniha: https://github.com/patterniha/SNI-Spoofing. Big thanks for the original idea and code that inspired this repository.

> <div style="color: #e83220; font-weight:500;">This software is provided as-is, without any warranty or guarantee of connectivity, reliability, or fitness for any particular purpose. Use it at your own risk. The user is solely responsible for any outcomes, issues, or consequences that may arise from using this project.</div>

RM SNI Spoofer is a Windows-only local TCP relay that injects a decoy TLS ClientHello with a spoofed SNI, then forwards the real traffic normally. The fake packet is sent with an intentionally wrong TCP sequence number so packet filters can see it on the wire without it becoming part of the live stream.

The app also includes a desktop control panel for managing Xray share links, starting and stopping the relay, and running delay tests. The codebase is split across GUI orchestration, runtime control, Xray helpers, packet injection, and subprocess wrappers instead of a single monolithic entry point.

## What It Does

For each incoming TCP connection, the program listens on `LISTEN_HOST:LISTEN_PORT`, opens an outbound connection to the configured `CONNECT_IP`, watches that connection with WinDivert through `pydivert`, injects the fake TLS handshake, and then relays bytes in both directions without modifying the real payload.

If an active Xray profile is configured, the app starts the bundled `xray.exe` process. In the proxy-based modes, Xray exposes one local mixed proxy on `127.0.0.1:LOCAL_PROXY_PORT`, and its outbound traffic is rewired back to the local relay listener. In `tunnel whole system` mode, Xray creates a Wintun-backed TUN adapter and the app takes ownership of the default IPv4 route, a direct exclusion route for `CONNECT_IP`, and the tunnel adapter DNS settings while the relay is running.

The connection mode controls what the app owns while the relay is running:

- `clear system proxy`: the app clears the Windows system proxy while keeping the local mixed proxy available for manual clients.
- `set system proxy`: the app points the Windows system proxy at `127.0.0.1:LOCAL_PROXY_PORT` while the relay is running.
- `tunnel whole system`: the app uses the bundled Xray TUN backend with `wintun.dll`, moves the default IPv4 route onto the Xray adapter, pins `CONNECT_IP` outside the tunnel, applies `TUNNEL_DNS_SERVERS` to the tunnel adapter, and restores those changes on stop or stale-state repair. This mode requires administrator rights and carries UDP traffic through the tunnel backend.

The GUI stores direct `vless://` and `trojan://` share links in an `XRAY Profiles` table, lets you mark one row active, and runs delay tests for selected rows. Only the active profile powers the relay. The profile table supports multi-row copy, direct clipboard paste, and bulk add through the add dialog by entering one share link per line. Profile add, edit, remove, and active-row changes remain available while the relay is already running. Delay tests are available only in the proxy-based modes, can run while the main relay is already running, and remain blocked while `tunnel whole system` is selected.

## Key Limits

- Windows only.
- IPv4 only in the current entry point.
- The proxy-based relay path is TCP-only; UDP works in `tunnel whole system` mode through the bundled Xray TUN backend.
- One fixed upstream destination per run.
- `wrong_seq` is the only active bypass method.
- Share-link mode expects port `443` unless `FORCE_CONNECT_PORT` is enabled.

## Project Layout

- `src/main.py`: canonical command-line bootstrap and `--headless` entry point.
- `src/gui/window.py`: desktop control panel shell and layout orchestration.
- `src/gui/relay.py`: relay start/stop actions, delay-test actions, and config assembly from GUI state.
- `src/gui/profiles.py`: profile-table behavior, selection state, and persistence glue.
- `src/gui/logs.py`: log queue routing and display formatting.
- `src/gui/editor.py`: reusable text and context-menu helpers.
- `src/gui/dialogs.py`: support, help, and share-link dialogs.
- `src/gui/widgets.py`: custom panels and buttons.
- `src/gui/theme.py`: theme tokens, icons, and style setup.
- `src/core/config/app_config.py`: config loading, normalization, and profile record helpers.
- `src/core/runtime/runtime_controller.py`: mode-aware runtime ownership, startup, shutdown, and stale-state repair.
- `src/core/runtime/runtime_state.py`: shared runtime settings, runtime-path resolution, and Xray startup decisions.
- `src/core/runtime/tunnel_backend.py`: bundled Xray TUN backend, route ownership, DNS ownership, and stale tunnel cleanup.
- `src/core/runtime/relay_server.py`: headless relay startup and accept-loop orchestration.
- `src/services/relay_runtime.py`: GUI subprocess launcher for the headless runtime.
- `src/services/delay_test.py`: temporary relay and proxy runtime for delay probes.
- `src/core/xray/config.py`: Xray share-link parsing and config generation.
- `src/core/xray/process.py`: bundled Xray process lifecycle.
- `src/core/packet_injection/`: WinDivert wrapper, per-connection state, and fake packet injection.
- `src/utils/network_tools.py` and `src/utils/packet_templates.py`: low-level network and TLS packet helpers.
- `src/assets/`: packaged fonts, icons, and app logos.

## Configuration

Runtime settings live in `config.json`. The most important fields are `LISTEN_HOST`, `LISTEN_PORT`, `CONNECT_IP`, `CONNECT_PORT`, `FORCE_CONNECT_PORT`, `FAKE_SNI`, `CONNECTION_MODE`, `LOCAL_PROXY_BIND_HOST`, `LOCAL_PROXY_PORT`, `TUNNEL_DNS_SERVERS`, `XRAY_PROFILES`, `XRAY_ACTIVE_PROFILE_ID`, `XRAY_BINARY_PATH`, `XRAY_LOG_LEVEL`, and `XRAY_RELAY_HOST`.

`TUNNEL_DNS_SERVERS` is a list of IPv4 DNS servers that the app applies to the Xray tunnel adapter while `tunnel whole system` is active. The current default is Cloudflare IPv4 (`1.1.1.1`, `1.0.0.1`).

`LOCAL_PROXY_BIND_HOST` controls which IPv4 address the local Xray mixed proxy binds to. The default is `127.0.0.1`. Set it to `0.0.0.0` only when you intentionally want other devices on the same LAN to use the proxy, because the mixed proxy is unauthenticated. If Windows Firewall prompts while LAN sharing is enabled, allow the app only on private or otherwise trusted networks.

`FAKE_SNI` only changes the spoofed value in the injected packet. It does not affect DNS resolution or choose the upstream IP.

The GUI reads these values from disk at startup and builds temporary runtime configs from the current form values when starting the relay or running delay tests. Profile add, edit, remove, and active-row changes are handled through the GUI helpers in `src/gui/profiles.py`.

Connection-mode and mixed-port planning is documented in `implementation-docs/plan-connection-mode.md` and `implementation-docs/plan-connection-mode-todo.md`. The current release uses one mixed local proxy port for the proxy-based modes and supports `tunnel whole system` through the bundled Xray TUN backend for TCP-oriented traffic.

## Requirements

- Windows
- Python 3.11
- `pydivert`
- WinDivert support available to `pydivert`
- `xray\\xray.exe` when using the Xray/profile flow
- `xray\\wintun.dll` beside `xray\\xray.exe` when using `tunnel whole system`
- Administrator privileges are usually required for packet capture and injection, and are required for `tunnel whole system`

Install dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python -m src
```

This opens the GUI by default. Use `python -m src --headless` for console-only relay mode, and add `--config path\to\config.json` to point at a different config file.

When Xray is active in the proxy-based modes, the app exposes a local mixed proxy on `127.0.0.1:LOCAL_PROXY_PORT`.

In `clear system proxy` mode, Windows proxy settings are cleared while the relay is running. In `set system proxy` mode, Windows proxy settings are temporarily pointed at `127.0.0.1:LOCAL_PROXY_PORT` and restored when the relay stops.

In `tunnel whole system` mode, the app must be started as Administrator. While that mode is running, the app brings up the bundled Xray TUN adapter, installs a direct `/32` route for `CONNECT_IP` through the pre-tunnel gateway, moves the default IPv4 route to the tunnel adapter, applies `TUNNEL_DNS_SERVERS` to the tunnel adapter, and restores those app-owned route and DNS changes when the relay stops or stale tunnel state is repaired.

Delay tests remain limited to the proxy-based modes because they use isolated temporary runtimes and should not take over system routes, DNS, or the running relay's ownership state.

## Build

To create a Windows bundle containing the exe, `config.json`, assets from `src/assets/`, and the runtime files under `xray\\`:

```powershell
pip install -r requirements-build.txt
python build.py
```

Use `python build.py --force-connect-port` if you want the bundled config to always use `CONNECT_PORT` instead of the port from an active share link.

`build.py` packages `src/main.py` as the application entry point and stages fonts, icons, logos, and the bundled Xray runtime directory.

The output bundle is written to `dist\\RM SNI Spoofer\\`.

## Notes

- The relay is low-level and timing-sensitive.
- Packet injection failures or unexpected packets close the connection.
- If the chosen `CONNECT_IP` does not actually serve the expected site, the later TLS handshake will still fail.
- Relay start and delay tests require an active Xray profile.
- Delay test results are persisted in `config.json` and restored the next time the app opens.
- The app restores the previous Windows proxy state on normal stop when it changed that state itself.
- Tunnel mode restores its app-owned routes and tunnel adapter DNS state on normal stop and stale-state repair.
- UDP works in `tunnel whole system` mode through the bundled Xray TUN backend when an active Xray profile is configured.

## License

This repository includes the GNU GPL v3 license in `LICENSE`.
