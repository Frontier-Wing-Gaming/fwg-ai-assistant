# Deployment and updates

## Fresh installation

Extract the release into its own directory; do not extract it over a running pilot folder. Run `python3 deploy.py install` from the release root. It asks for your browser origin, Pterodactyl HTTPS origin, restricted Client API key, owner password and server aliases/identifiers. Identifiers are from the panel's server URLs, not numeric server IDs.

The owner starts with status/resource/log access. The wizard explicitly asks whether power actions should be allowed. Each start/stop/restart request still requires a separate confirmation. No power changes occur during setup.

The assistant listens on host loopback port 8099. Ollama has no host-published port. Default CPU limits are four cores for Ollama and two for the assistant, with RAM limits of 8 GB and 4 GB respectively. These are caps, not a promise of idle memory usage: speech models and a loaded language model consume RAM. Calls use CPU while processing; idle usage is lower. Check your actual host load.

`docker compose` automatically loads `compose.override.yaml` when the NPM network option is selected. The named external network must already exist and contain the NPM container. In NPM create your proxy host using HTTP, hostname `fwg-ai-assistant`, port `8000`; enable HTTPS and force SSL. Match `APP_ORIGIN` exactly, including scheme and any nonstandard port. NPM is not used for SIP or RTP.

If you decline a proxy network, the example override can be copied and edited later. After changes, run `docker compose up -d --force-recreate assistant` inside `assistant/`. Recreating is required after `.env` changes; `restart` alone does not reload container environment variables.

## Phone and monitor stages

The install wizard can start LAN SIP and PIN authentication. Test extension 700 before enabling public routing. Optional subsequent stages:

```bash
python3 deploy.py provider
python3 deploy.py public-phone
python3 deploy.py callshield
python3 deploy.py monitor
```

Public routing and CallShield need your DID assignment and router media configuration. See [PHONE.md](PHONE.md). These commands configure the new release's `phone/` deployment. For an existing pilot use the integration scripts directly with `--pilot` and `--assistant` paths rather than running fresh setup.

The monitor runs once every two minutes through the installing user's crontab. It retains unrelated jobs, alerts after three consecutive failed checks, and recovers after two good checks. Discord delivery failures are retried. It does not generate an LLM response for health checks. Use `python3 monitor/monitor.py --test-webhook` to test delivery, or `--status` to read the saved state. Select only containers and games you expect to stay running.

## Pterodactyl subuser permissions per server

Give a dedicated restricted panel user only the permissions corresponding to enabled assistant actions. Use its Client API key, never an Application API key or the panel owner's key.

| Assistant function | Panel subuser permission |
| --- | --- |
| Status and resource usage | Access as a subuser assigned to that server; no start/stop/restart permission needed |
| Recent console output | Control → Console (`control.console`); a websocket token is needed by the API, but no separate websocket checkbox is normally shown |
| Start | Control → Start (`control.start`) |
| Stop | Control → Stop (`control.stop`) |
| Restart | Control → Restart (`control.restart`) |

Console access also grants broader abilities in the panel than this assistant exposes. The assistant only requests recent logs; it never sends arbitrary console commands. Disable the assistant's `logs` action if console text should not be exposed to a user. File, database, backup, startup, allocation, schedule and subuser management permissions are unnecessary for these functions.

## Existing pilot update

Stop active calls before upgrading. Keep the existing deployment paths; changing directories/project names can create different named model volumes. Run the root `deploy.py update` with explicit existing paths as shown in the README. Existing `.env`, `users.json`, `servers.json`, SIP settings, dialplan, Compose and proxy overrides remain in place. If the old deployment has no `PIPER_VOICE` setting, the updater explicitly retains the previous Lessac voice. A fresh install defaults to LJ Speech high; performance can differ from previous benchmark results.

An existing CallShield installation and its cron schedule remain in place. Its scripts can be updated separately from `integrations/callshield/` after reviewing the installed layout. The code updater does not replace your feed database or reconstruct phone routes.

The updater saves old code and the environment under a mode-700 `backups/` folder. If a command fails, previous files are restored; any already-created containers can still use the newer image. Rebuild/recreate from restored files to complete runtime rollback. Restoring files is not an image rollback. Private snapshots must never be uploaded to GitHub.

## Check operation

```bash
python3 deploy.py status
cd assistant
docker compose logs --tail=50 assistant
```

Health returns HTTP 503 while models initialize, then 200 with `ready: true`. If first-run initialization fails, inspect connectivity/downloads and restart the assistant. The installer waits up to 15 minutes, then leaves the containers in place for troubleshooting. It never runs `docker compose down -v`.

Acceptance tests: web login; status/resources/logs with a restricted account; denied action and wrong-server requests; one confirmed restart on a disposable test server; LAN SIP registration/PIN; two-way audio; public whitelisted and unknown calls; a synthetic blocked number in a test dialplan; Discord failure/recovery notifications. Public calls and forwarding may incur provider charges.
