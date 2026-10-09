# FWG AI Assistant

Self-hosted web and telephone assistant for a homelab and Pterodactyl game servers. CPU-first, with local Qwen3 1.7B, Whisper transcription and Piper speech.

**Beta release.** The application and LAN phone components have been exercised in a homelab. The consolidated installer has automated configuration tests; a fresh end-to-end Docker deployment and public telephone acceptance tests are still required. This is not a general shell agent or an emergency telephone service.

## Deploy

On an Ubuntu Linux host with Docker Engine, the Docker Compose plugin and Python 3:

```bash
sudo apt install python3-venv cron
python3 deploy.py install
```

The wizard collects private settings locally, creates the owner account, adds game servers and starts the assistant. LAN phone and Discord monitoring are optional. Docker access for the installing user is required; membership in the Docker group gives powerful host access. A first installation downloads models and may take several minutes. Building Asterisk from source takes additional time.

Nginx Proxy Manager can share its existing Docker network with the assistant. You configure the HTTPS proxy host yourself; no NPM login is collected. Local access uses `http://localhost:8099` through a tunnel or on the host.

See [deployment](docs/DEPLOYMENT.md), [phone setup](docs/PHONE.md), [accounts](docs/ACCOUNTS.md), [security](SECURITY.md) and [third-party licenses](docs/THIRD_PARTY.md).

## Included

| Component | Behavior |
| --- | --- |
| Web assistant | Text or recorded voice; individual local web accounts |
| Pterodactyl | Status, resources, recent console lines; confirmed start, stop and restart |
| LAN telephone | SIP extension 1001, assistant extension 700, PIN authentication |
| VoIP.ms | Chicago1 TLS/SRTP trunk; incoming DID routing and one fixed forwarding number |
| Incoming routing | Admin caller whitelist plus shared PIN; other callers press 5 before forwarding |
| CallShield | Signed exact-number US/Canada list; matching non-admin callers rejected |
| Discord monitor | Docker, HTTPS sites, optional panel resources, disk and memory alerts |

Arbitrary outbound AI conversations, shell commands, backup creation, per-caller phone accounts, caller-name lookup and provider CNAM provisioning are not implemented. The only outbound public call path is forwarding to the configured fixed number. Phone access uses one configured assistant account and a shared PIN; use a restricted account when appropriate. Caller ID alone is not trusted authentication.

## Upgrade an existing pilot

Keep its existing folders and Docker Compose project names. Run this release's update command with the three existing deployment paths:

```bash
python3 deploy.py update \
  --assistant /absolute/path/to/fwg-assistant-pilot \
  --phone /absolute/path/to/fwg-phone-pilot \
  --monitor /absolute/path/to/fwg-discord-monitor
```

It replaces application code and rebuilds configured containers. It retains private accounts, server mappings, phone routing, Compose overrides and named volumes. It creates a private local rollback snapshot, and does not remove Docker volumes. It does not silently install new provider routing or CallShield into an existing deployment. Those integrations remain deliberate setup stages.

For subsequent updates to a fresh deployment in this directory: `python3 deploy.py update`.

## Tests

Python 3.12 is used for CI and containers. Configuration tests use synthetic data, mock panel requests and generated signing keys; they do not make real calls or change a live server.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python scripts/test_all.py
```

Runtime model files, private settings, call recordings, spam databases and logs are excluded from source releases. First-party source is GPL-3.0-or-later; dependencies and downloadable models have their own terms. See [LICENSE](LICENSE) and [third-party notices](docs/THIRD_PARTY.md).
