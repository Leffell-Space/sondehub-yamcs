# Validation scope

## Standalone cleanup — October 18, 2026

The project now contains only bridge code, its container/configuration, documentation, and tests. Station setup, Yamcs server sources, intercom, generated credentials/data, and old combined-package integration tools were preserved outside the project in the sibling `spacestation02-setup-archive` folder. That folder is historical material, not a runnable standalone deployment.

**11 unit tests passed locally on October 18 after the separation.** All Python source files also passed syntax compilation.

Current unit coverage: complete raw-field preservation, collision-free names, missing/invalid measurements, timestamp validation, changing field types, SQLite connection cleanup, filtered receipt deduplication, multiple-balloon/multiple-instance routing, private configuration creation, refusal to overwrite secrets, and rejection of unsafe configuration URLs.

## Historical real integration — October 14, 2026

An actual Yamcs 5.13.0 Java process on macOS was tested with the bridge: dynamic parameter creation, acknowledged ingestion, live reads, archive replay, late-packet isolation, WebSocket updates and expiry, authentication/authorization, two balloons with distinct values, and persistence after Yamcs restart. The old integration harness and detailed results are preserved with the station archive.

A live read-only SondeHub Amateur discovery request and MQTT connection/subscription acknowledgements succeeded. This did **not** demonstrate receipt from HAB-2. No telemetry was uploaded to SondeHub.

## Not yet demonstrated

- The new standalone Docker Compose deployment on Fedora, including SELinux, host networking, image build/start, and reboot recovery. Docker is unavailable on this development machine.
- An actual HAB-2 tracker packet reaching SondeHub Amateur, Yamcs, Spacecast, and an OBS recording.
- Extended outages/load, operational queue recovery, disk capacity, and the final Tailscale access policy.

Historical native-process results are not a fresh container test or a flight rehearsal. Complete the README rehearsal and real-tracker checks on spacestation02 before relying on the system for launch.
