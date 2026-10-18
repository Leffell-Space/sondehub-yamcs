# SondeHub Amateur → Yamcs bridge

Bridge-only Python application and Docker Compose deployment. Connects to an **existing Yamcs server**; does not install Yamcs, create instances, install Spacecast, or deploy intercom.

## What it does

- Subscribes to SondeHub **Amateur** MQTT topics `amateur/<payload_callsign>` over TLS WebSockets, with reconnects. This is separate from ordinary radiosonde topics.
- Authenticated web console: discover recently heard Amateur balloons and their fields, add callsigns before launch, and route multiple balloons to existing Yamcs instances without code changes. One callsign can target multiple instances.
- Preserves the complete received JSON, exposes custom fields as typed parameters, and provides stable navigation parameters and a Spacecast parameter-map export. Objects/arrays are retained as JSON strings.
- SQLite receipt journal persists received packets before forwarding; retries acknowledged Yamcs HTTP ingestion. Fresh packets enter `pp_realtime`; late packets enter archive-only `pp_dump` to avoid replacing live telemetry with old positions.

One deployment connects to one Yamcs server URL and multiple instances on that server. Use separate deployments for different servers (with different console ports; this Compose file uses 8088).

## Existing Yamcs requirements

Validated previously with Yamcs **5.13.0**. Each target needs:

1. A running processor named `realtime`, with `StreamParameterProvider` consuming `pp_realtime`.
2. Parameter streams `pp_realtime` and `pp_dump`; a `ParameterRecorder` recording both for history. Do not feed `pp_dump` into the live processor. Archive replay requires the server's replay configuration.
3. A writable XTCE mission database rooted at `/HAB`, persisted on disk. The bridge creates parameter definitions through the dynamic MDB API (experimental in Yamcs).
4. An authenticated bridge account with `ReadParameter` and `WriteParameter` matching `/HAB/.*`, and system privileges `GetMissionDatabase` and `ChangeMissionDatabase`.

A default arbitrary Yamcs instance may need these changes before it can accept this bridge. Provision instances on Yamcs first, then select them in the bridge. The bridge does not create launch instances. Spacecast should use a separate read-only Yamcs account and the exported parameter names.

## Start on Fedora/Linux

Prerequisites: Python 3, Docker Engine with Compose plugin, and the configured Yamcs server above. From this project's directory:

```bash
python3 configure.py
sudo docker compose up -d --build
sudo docker compose logs --tail=100 bridge
```

The setup prompts for the existing Yamcs URL and account password. It writes private, git-ignored `data/secrets.json`, `data/config.json`, and `.env`; it refuses to overwrite credentials. Default Yamcs URL is `http://127.0.0.1:8090`. Use HTTPS for a remote server.

Open `http://127.0.0.1:8088` on the station. Username: `operator`; password: `console_password` in `data/secrets.json`. Add each exact, case-sensitive Amateur payload callsign and its existing Yamcs instance. You can configure a future balloon before SondeHub has heard it. Discovery is a recent snapshot, not a registry of future flights.

Compose uses **Linux host networking** so it can reach an existing Yamcs published on host localhost. The console binds to localhost only. The `:Z` data mount supports Fedora SELinux. Expose the console remotely using a private HTTPS proxy such as Tailscale Serve. Keep its operator password enabled.

To check startup (replace the instance name):

```bash
sudo docker compose exec bridge python check_ready.py hab2
```

This checks the processor and console, not reception of flight telemetry. The console shows receipt/forwarding errors and journal counts. Its Spacecast export provides parameter mappings; it does not modify Spacecast.

## Rehearse before flight

Create a separate Yamcs instance whose name includes `rehearsal`, configure `TEST-HAB` to target it in the console, then run:

```bash
sudo docker compose exec bridge python rehearse.py hab2-rehearsal
```

Synthetic telemetry stays local; nothing is uploaded to SondeHub. Then verify a real tracker packet through SondeHub Amateur → bridge → Yamcs → Spacecast → OBS. Check timestamps and expiry, reboot recovery, and cellular connectivity.

## Operational limits

- This forwards what SondeHub Amateur publishes; it does not receive APRS-IS or Horus RF directly. Your receiver/uploader must get those packets into SondeHub Amateur first.
- MQTT uses QoS 0. Packets missed while disconnected are not automatically backfilled. SQLite protects packets already received, not packets never received. HTTP retries are at-least-once, so an acknowledgement lost in transit can cause a duplicate in Yamcs.
- Invalid timestamps remain in the local raw journal with an error; they are not published as live telemetry. Default freshness/expiry is 30 seconds; adjust `expire_seconds` in `data/config.json` and restart if the actual tracker cadence needs longer.
- One worker serves all targets: a broken target can delay others. Test every configured instance before launch.
- The journal grows without automatic retention. Monitor disk space; back up `data/` while stopped, plus Yamcs's writable MDB and archive separately. Protect credentials and never commit `data/` or `.env`.

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r bridge/requirements.txt
.venv/bin/python -W ignore -m unittest discover -s tests -v
```

See [VALIDATION.md](VALIDATION.md) for the distinction between unit tests, historical real-Yamcs validation, and target-machine checks still required. GitHub Actions runs unit tests, Compose validation, and a bridge image build; it does not run a Yamcs server.
