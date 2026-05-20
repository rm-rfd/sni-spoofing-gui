# SNI-Spoofing-GUI

This project is built on top of the work by Patterniha: https://github.com/patterniha/SNI-Spoofing. Big thanks for the original idea and code that inspired this repository.

This software is provided as-is, without any warranty or guarantee of connectivity, reliability, or fitness for any particular purpose. Use it at your own risk. The user is solely responsible for any outcomes, issues, or consequences that may arise from using this project.

This project is a Windows-only local TCP relay that tries to bypass simple DPI rules by injecting a fake TLS ClientHello with a decoy SNI during the outbound TCP handshake.

The important detail is that the injected packet is not meant to become part of the real TCP stream. The code sends that fake ClientHello with an intentionally wrong TCP sequence number so middleboxes can still see it on the wire, while the upstream server is expected to treat it as invalid or out-of-window data and continue waiting for the real application bytes.

After that fake packet is sent, the program stops packet interception for the connection and relays traffic normally between the local client and the configured upstream socket.

When `XRAY_URL` is configured, the program also starts a bundled `xray.exe` child process. Xray exposes local SOCKS5 and HTTP proxy ports, and its outbound talks to this relay listener.

You can now paste the original remote `vless://` or `trojan://` share link into `XRAY_URL`. The app rewrites the Xray dial target to the local relay automatically while preserving the original transport and TLS settings from the share link.

For this app to work in share-link mode, the remote port must be `443`. Other remote ports are not supported by this relay flow.

## What The Program Actually Does

For each incoming TCP connection:

1. It listens on `LISTEN_HOST:LISTEN_PORT`.
2. It opens a real outbound TCP connection to the fixed upstream target `CONNECT_IP` on the port derived from `XRAY_URL` when present, or from the legacy `CONNECT_PORT` fallback otherwise.
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

The app now also ships with a small desktop control panel. It edits the most common runtime fields in `config.json`, starts and stops the relay, can run a V2rayN-style delay test, and shows live process output in one window.

## Current Implementation Limits

The current codebase is intentionally narrow:

- Only Windows is supported because packet capture and injection are implemented with WinDivert via `pydivert`.
- Only IPv4 is used in the active entry point.
- Only TLS mode is implemented in `main.py`.
- Only the `wrong_seq` bypass method is active.
- Only one fake SNI is configured for the whole process.
- The program forwards to one configured upstream endpoint, not many.
- There is no UDP or QUIC support.
- SOCKS, HTTP, and supported Xray share links are handled by the bundled Xray child process when `XRAY_URL` is configured.

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
  "XRAY_URL": "vless://<uuid>@server.example:443?...",
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
- `XRAY_URL`: the original Xray share link. `vless://`, `trojan://`, and other supported Xray share URLs are accepted. Its remote port is also used as the relay's upstream TCP port when this field is set, and it must be `443` for the relay flow to work.
- `FAKE_SNI`: the decoy SNI inserted into the synthetic ClientHello.
- `CONNECT_PORT`: optional legacy fallback port used only when `XRAY_URL` is empty. If omitted, it defaults to `443`.
- `XRAY_BINARY_PATH`: path to the bundled Xray executable.
- `XRAY_SOCKS_PORT`: local SOCKS5 listen port for the Xray child process. The host is always `127.0.0.1`.
- `XRAY_HTTP_PORT`: local HTTP proxy listen port for the Xray child process. The host is always `127.0.0.1`.
- `XRAY_LOG_LEVEL`: Xray log level used for the generated runtime config.
- `XRAY_RELAY_HOST`: optional override for the address Xray uses to reach the local relay. If omitted, the app derives a loopback-safe default from `LISTEN_HOST`.

`FAKE_SNI` is the spoofed value shown in the fake packet. It is not used for DNS resolution and it does not change which remote IP the socket connects to.

The control panel edits these fields directly in `config.json`:

- `CONNECT_IP`
- `FAKE_SNI`
- `XRAY_URL`
- `XRAY_SOCKS_PORT`
- `XRAY_HTTP_PORT`
- `XRAY_LOG_LEVEL`

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

That command now opens the desktop control panel. From there you can save the selected config fields, start or stop the relay, run a delay probe, and inspect logs without opening `config.json` in a text editor.

If you want the previous console-only behavior, run:

```powershell
python main.py --headless
```

If you need to run the relay against an alternate config file, you can override the path explicitly:

```powershell
python main.py --headless --config path\to\config.json
```

If `XRAY_URL` is configured, the app starts bundled Xray and exposes these local proxies on fixed loopback addresses:

- SOCKS5: `127.0.0.1:XRAY_SOCKS_PORT`
- HTTP: `127.0.0.1:XRAY_HTTP_PORT`

Applications can use those proxy ports directly without running V2rayN.

The `Test Delay` button uses an isolated temporary runtime instead of reusing the saved relay ports. It chooses fresh local ports that do not collide with `LISTEN_PORT`, `CONNECT_PORT`, `XRAY_SOCKS_PORT`, or `XRAY_HTTP_PORT`, launches a temporary headless relay plus bundled Xray, opens a CONNECT tunnel through the temporary HTTP proxy, and measures a single HTTPS GET to `https://www.google.com/generate_204` through that tunnel. Stop the main relay before running the delay probe.

The relay still listens on `LISTEN_HOST:LISTEN_PORT`, and Xray reaches it through `XRAY_RELAY_HOST:LISTEN_PORT`.

When `XRAY_URL` contains the original remote host and port, the app rewrites Xray to dial `XRAY_RELAY_HOST:LISTEN_PORT` instead. This means you no longer need to manually edit the share link to `127.0.0.1:40443`.

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

The output bundle is written to `dist\\SNI-Spoofing\\`.

The bundled executable opens the control panel by default. Use `SNI-Spoofing.exe --headless` if you need the relay without the GUI.

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
