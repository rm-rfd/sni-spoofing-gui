# SNI-Spoofing-GUI

This project is built on top of the work by Patterniha: https://github.com/patterniha/SNI-Spoofing. Big thanks for the original idea and code that inspired this repository.

This software is provided as-is, without any warranty or guarantee of connectivity, reliability, or fitness for any particular purpose. Use it at your own risk. The user is solely responsible for any outcomes, issues, or consequences that may arise from using this project.

This project is a Windows-only local TCP relay that tries to bypass simple DPI rules by injecting a fake TLS ClientHello with a decoy SNI during the outbound TCP handshake.

The important detail is that the injected packet is not meant to become part of the real TCP stream. The code sends that fake ClientHello with an intentionally wrong TCP sequence number so middleboxes can still see it on the wire, while the upstream server is expected to treat it as invalid or out-of-window data and continue waiting for the real application bytes.

After that fake packet is sent, the program stops packet interception for the connection and relays traffic normally between the local client and the configured upstream socket.

When an active Xray profile is configured, the program also starts a bundled `xray.exe` child process. Xray exposes local SOCKS5 and HTTP proxy ports, and its outbound talks to this relay listener.

In GUI mode, you can store multiple direct `vless://` or `trojan://` share links in an `XRAY Profiles` table, mark one row as active, and run delay tests for one or many selected rows. The app rewrites only the active share link's dial target to the local relay while preserving the original transport and TLS settings from the share link.

For this app to work in share-link mode, the remote port must be `443`. Other remote ports are not supported by this relay flow.

## What The Program Actually Does

For each incoming TCP connection:

1. It listens on `LISTEN_HOST:LISTEN_PORT`.
2. It opens a real outbound TCP connection to the fixed upstream target `CONNECT_IP` on the port derived from the active Xray profile when present, or from the `CONNECT_PORT` fallback otherwise.
3. It uses WinDivert through `pydivert` to watch the packets of that outbound connection.
4. Right after the normal TCP three-way handshake, it injects an extra ACK+PSH packet that contains a synthetic TLS ClientHello.
5. That synthetic ClientHello contains the configured `FAKE_SNI` value.
6. The injected packet uses the `wrong_seq` method, meaning the TCP sequence number is intentionally shifted so the packet should not be accepted as real application data by the server.
7. Once the fake packet attempt is complete, the code turns interception off for that connection and starts relaying bytes in both directions without modifying the real payload.

In short: this is not rewriting the real TLS handshake in transit. It is sending a decoy TLS ClientHello before relaying the real client traffic.

## What It Is Not

- It is not a VPN.
- The relay code itself is not a SOCKS proxy implementation.
- The relay code itself is not an HTTP CONNECT proxy implementation.
- It is not a general-purpose TLS terminator.
- It does not dynamically choose an upstream host per connection.
- It does not resolve hostnames from client traffic.

The upstream destination is fixed in `config.json`, so every accepted local connection is forwarded to the same remote IP and port.

The app now also ships with a small desktop control panel. It loads the most common runtime fields and the persisted Xray profile list from `config.json`, starts and stops the relay, can run a V2rayN-style delay test across selected rows, and shows live process output in one window.

## Current Implementation Limits

The current codebase is intentionally narrow:

- Only Windows is supported because packet capture and injection are implemented with WinDivert via `pydivert`.
- Only IPv4 is used in the active entry point.
- Only TLS mode is implemented in `main.py`.
- Only the `wrong_seq` bypass method is active.
- Only one fake SNI is configured for the whole process.
- The program forwards to one configured upstream endpoint, not many.
- The GUI can store many direct share links, but only one active profile powers the relay at a time.
- Remote subscription URL import is not implemented yet; the first version supports direct share links only.
- There is no UDP or QUIC support.
- SOCKS, HTTP, and supported Xray share links are handled by the bundled Xray child process when an active Xray profile is configured.

## How The Code Is Organized

- `main.py`: loads `config.json`, optionally starts bundled Xray, accepts local TCP connections, creates the outbound socket, and relays traffic after the injection phase.
- `fake_tcp.py`: tracks the TCP handshake and injects the fake ClientHello packet.
- `injecter.py`: wraps WinDivert packet capture/send operations.
- `monitor_connection.py`: stores the per-connection state used during packet monitoring.
- `utils/packet_templates.py`: builds the fake TLS ClientHello payload.
- `utils/network_tools.py`: discovers the local IPv4 address used to reach the configured upstream IP.
- `utils/delay_test.py`: launches a temporary relay and bundled Xray on random local ports, then measures a TCP connect to `google.com:443` through the generated HTTP proxy.
- `utils/xray.py`: parses supported Xray share links, generates the Xray JSON config, validates it, and manages the Xray child process.

## Configuration

The runtime behavior is controlled by `config.json`:

```json
{
  "LISTEN_HOST": "0.0.0.0",
  "LISTEN_PORT": 40443,
  "CONNECT_IP": "188.114.98.0",
  "CONNECT_PORT": 443,
  "FAKE_SNI": "auth.vercel.com",
  "XRAY_PROFILES": [
    {
      "id": "primaryprofile",
      "url": "vless://<uuid>@server.example:443?...#Primary",
      "tag": "Primary",
      "protocol": "vless",
      "address": "server.example",
      "port": 443,
      "transport": "ws",
      "security": "tls"
    }
  ],
  "XRAY_ACTIVE_PROFILE_ID": "primaryprofile",
  "XRAY_BINARY_PATH": "xray\\xray.exe",
  "XRAY_SOCKS_PORT": 10908,
  "XRAY_HTTP_PORT": 10909,
  "XRAY_LOG_LEVEL": "warning",
  "XRAY_RELAY_HOST": "127.0.0.1"
}
```

- `LISTEN_HOST`: local bind address for the relay.
- `LISTEN_PORT`: local TCP port that clients connect to.
- `CONNECT_IP`: fixed remote IPv4 address the program will connect to.
- `XRAY_PROFILES`: persisted list of direct `vless://` or `trojan://` share links shown in the GUI table. Each row stores the raw URL plus derived metadata such as `tag`, `protocol`, `address`, `port`, `transport`, and `security`.
- `XRAY_ACTIVE_PROFILE_ID`: id of the active row in the GUI. `Start Relay` always uses this row only.
- `FAKE_SNI`: the decoy SNI inserted into the synthetic ClientHello.
- `CONNECT_PORT`: optional fallback port used only when no active profile is available. If omitted, it defaults to `443`.
- `XRAY_BINARY_PATH`: path to the bundled Xray executable.
- `XRAY_SOCKS_PORT`: local SOCKS5 listen port for the Xray child process. The host is always `127.0.0.1`.
- `XRAY_HTTP_PORT`: local HTTP proxy listen port for the Xray child process. The host is always `127.0.0.1`.
- `XRAY_LOG_LEVEL`: Xray log level used for the generated runtime config.
- `XRAY_RELAY_HOST`: optional override for the address Xray uses to reach the local relay. If omitted, the app derives a loopback-safe default from `LISTEN_HOST`.

`FAKE_SNI` is the spoofed value shown in the fake packet. It is not used for DNS resolution and it does not change which remote IP the socket connects to.

The control panel loads these fields from `config.json` when it opens:

- `CONNECT_IP`
- `FAKE_SNI`
- `XRAY_PROFILES`
- `XRAY_ACTIVE_PROFILE_ID`
- `XRAY_SOCKS_PORT`
- `XRAY_HTTP_PORT`
- `XRAY_LOG_LEVEL`

Profile add, edit, remove, and set-active actions are persisted to `config.json` immediately. Starting the relay or running a delay test still uses the current form values for that session only, so changes to `CONNECT_IP`, `FAKE_SNI`, `XRAY_SOCKS_PORT`, `XRAY_HTTP_PORT`, and `XRAY_LOG_LEVEL` are not persisted unless you edit `config.json` directly. Delay and status cells in the profile table are session-only and are cleared when the app restarts.

## Requirements

- Windows
- Python 3
- `pydivert`
- WinDivert support available to `pydivert`
- `xray\xray.exe`
- Administrator privileges are typically required to open WinDivert filters and inject packets

Install dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Running

```powershell
python main.py
```

That command now opens the desktop control panel. From there you can start or stop the relay, run a delay probe, and inspect logs without opening a separate console window.

The GUI workflow is:

- Use `Add`, `Edit`, `Remove`, and `Set Active` to manage direct share links in the `XRAY Profiles` table.
- `Start Relay` uses only the active row.
- `Test Delay` runs sequential probes for the selected row or rows without changing the active relay target.
- Delay results are written into the `Delay` and `Status` columns for the current session.

If you want the previous console-only behavior, run:

```powershell
python main.py --headless
```

If you need to run the relay against an alternate config file, you can override the path explicitly:

```powershell
python main.py --headless --config path\to\config.json
```

If an active Xray profile is configured, the app starts bundled Xray and exposes these local proxies on fixed loopback addresses:

- SOCKS5: `127.0.0.1:XRAY_SOCKS_PORT`
- HTTP: `127.0.0.1:XRAY_HTTP_PORT`

Applications can use those proxy ports directly without running V2rayN.

The `Test Delay` button uses an isolated temporary runtime instead of reusing the saved relay ports. For each selected row, it chooses fresh local ports that do not collide with `LISTEN_PORT`, `CONNECT_PORT`, `XRAY_SOCKS_PORT`, or `XRAY_HTTP_PORT`, launches a temporary headless relay plus bundled Xray, opens a CONNECT tunnel through the temporary HTTP proxy, and measures a single HTTPS GET to `https://www.google.com/generate_204` through that tunnel. Selected rows are tested sequentially, the active relay row is left unchanged, and the `Delay` and `Status` columns are updated for the current session only. Stop the main relay before running the delay probe.

The relay still listens on `LISTEN_HOST:LISTEN_PORT`, and Xray reaches it through `XRAY_RELAY_HOST:LISTEN_PORT`.

When the active profile contains the original remote host and port, the app rewrites Xray to dial `XRAY_RELAY_HOST:LISTEN_PORT` instead. This means you no longer need to manually edit the share link to `127.0.0.1:40443`.

Important operational notes:

- The Python relay still only relays raw TCP after the injection step.
- SOCKS and HTTP proxy support now come from the bundled Xray child process, not from custom Python protocol handling.
- The real TLS handshake still comes from the client traffic that gets relayed after the decoy packet.

## Build EXE

To build a distributable folder that already contains the exe, `config.json`, and `xray\\xray.exe`:

```powershell
pip install -r requirements-build.txt
python build.py
```

The output bundle is written to `dist\\SNI-Spoofing-GUI\\`.

The bundled executable opens the control panel by default. Use `SNI-Spoofing-GUI.exe --headless` if you need the relay without the GUI.

## Why This Can Work

Some DPI systems inspect packets on the wire without reproducing the full TCP state machine exactly the same way as the destination host. This project relies on that gap.

The intended behavior is:

- the DPI device sees the fake TLS ClientHello and its `FAKE_SNI`
- the upstream TCP stack ignores that fake segment because of the wrong sequence number
- the real client handshake arrives later through the normal socket relay

Whether that works depends on the specific network path, the DPI implementation, and how the remote stack handles out-of-window data. It is not guaranteed to work everywhere.

## Caveats

- This code is low-level and timing-sensitive.
- The logic assumes specific behavior from middleboxes and TCP stacks.
- Packet injection failures or unexpected packets cause the connection to be closed.
- If the chosen `CONNECT_IP` does not actually serve the site your client expects, the later TLS handshake will still fail.

## License

This repository includes the GNU GPL v3 license in `LICENSE`.
