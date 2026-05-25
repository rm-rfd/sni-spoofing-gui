# RM SNI Spoofer

This project is built on top of the work by Patterniha: https://github.com/patterniha/SNI-Spoofing. Big thanks for the original idea and code that inspired this repository.

> <div style="color: #e83220; font-weight:500;">This software is provided as-is, without any warranty or guarantee of connectivity, reliability, or fitness for any particular purpose. Use it at your own risk. The user is solely responsible for any outcomes, issues, or consequences that may arise from using this project.</div>

Windows-only local TCP relay that injects a decoy TLS ClientHello with a spoofed SNI, then forwards the real traffic normally. The fake packet is sent with an intentionally wrong TCP sequence number so packet filters can see it on the wire without it becoming part of the live stream.

The app also includes a small desktop control panel for managing Xray share links, starting and stopping the relay, and running delay tests.

## What It Does

For each incoming TCP connection, the program listens on `LISTEN_HOST:LISTEN_PORT`, opens an outbound connection to the configured `CONNECT_IP`, watches that connection with WinDivert through `pydivert`, injects the fake TLS handshake, and then relays bytes in both directions without modifying the real payload.

If an active Xray profile is configured, the app starts the bundled `xray.exe` process. Xray exposes local SOCKS5 and HTTP proxies, and its outbound traffic is rewired to the local relay listener.

The GUI stores direct `vless://` and `trojan://` share links in an `XRAY Profiles` table, lets you mark one row active, and runs delay tests for selected rows. Only the active profile powers the relay.

## Key Limits

- Windows only.
- IPv4 only in the current entry point.
- TCP relay only; no UDP or QUIC.
- One fixed upstream destination per run.
- `wrong_seq` is the only active bypass method.
- Share-link mode expects port `443` unless `FORCE_CONNECT_PORT` is enabled.

## Project Layout

- `main.py`: loads config, starts optional Xray, runs the relay, and provides `--headless`.
- `gui.py`: desktop control panel and profile management.
- `fake_tcp.py`: handshake tracking and fake packet injection.
- `injecter.py`: WinDivert wrapper.
- `monitor_connection.py`: per-connection state.
- `utils/packet_templates.py`: fake TLS ClientHello builder.
- `utils/network_tools.py`: finds the local IPv4 route for the upstream host.
- `utils/delay_test.py`: temporary relay and proxy runtime for delay probes.
- `utils/xray.py`: parses share links and builds Xray runtime config.

## Configuration

Runtime settings live in `config.json`. The most important fields are `LISTEN_HOST`, `LISTEN_PORT`, `CONNECT_IP`, `CONNECT_PORT`, `FORCE_CONNECT_PORT`, `FAKE_SNI`, `XRAY_PROFILES`, `XRAY_ACTIVE_PROFILE_ID`, `XRAY_BINARY_PATH`, `XRAY_SOCKS_PORT`, `XRAY_HTTP_PORT`, `XRAY_LOG_LEVEL`, and `XRAY_RELAY_HOST`.

`FAKE_SNI` only changes the spoofed value in the injected packet. It does not affect DNS resolution or choose the upstream IP.

The GUI persists profile add, edit, remove, and active-row changes immediately. The relay and delay-test inputs are read from the current session values, while the table's delay and status cells are session-only.

## Requirements

- Windows
- Python 3
- `pydivert`
- WinDivert support available to `pydivert`
- `xray\\xray.exe` when using the Xray/profile flow
- Administrator privileges are usually required for packet capture and injection

Install dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

This opens the GUI by default. Use `python main.py --headless` for console-only relay mode, and add `--config path\to\config.json` to point at a different config file.

When Xray is active, the app exposes local proxies on `127.0.0.1:XRAY_SOCKS_PORT` and `127.0.0.1:XRAY_HTTP_PORT`.

## Build

To create a Windows bundle containing the exe, `config.json`, fonts, icons, and `xray\\xray.exe`:

```powershell
pip install -r requirements-build.txt
python build.py
```

Use `python build.py --force-connect-port` if you want the bundled config to always use `CONNECT_PORT` instead of the port from an active share link.

The output bundle is written to `dist\\RM SNI Spoofer\\`.

## Notes

- The relay is low-level and timing-sensitive.
- Packet injection failures or unexpected packets close the connection.
- If the chosen `CONNECT_IP` does not actually serve the expected site, the later TLS handshake will still fail.

## License

This repository includes the GNU GPL v3 license in `LICENSE`.
