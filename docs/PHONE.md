# Telephone setup

LAN setup requires a private IPv4, your actual allowed LAN CIDR, unused UDP 5060, loopback TCP 9092 and UDP media ports 10000–10019. `phone/softphone-settings.txt` contains the generated SIP password; read it locally and never upload it. Use UDP without STUN/ICE for the initial LAN test. Dial 700, enter the 6–10 digit PIN followed by `#`, and ask for a test server's status. The account's allowlist/actions still apply. Confirm power changes using the DTMF confirmation prompted by the assistant. A shared PIN is used for all admitted phone callers.

LAN SIP is unencrypted: keep it on a trusted LAN or VPN and never forward UDP 5060 to the Internet. Asterisk and the bridge use host networking. The bridge binds loopback only and talks to the loopback assistant HTTP port with a generated bearer token.

## VoIP.ms

This integration currently targets `chicago1.voip.ms`. Create a dedicated subaccount, enable encrypted SIP traffic, set appropriate spending/call restrictions in your provider account and assign your DID to that subaccount on the same POP. Enter its complete SIP username and password locally when running `python3 deploy.py provider`. TLS signaling uses 5061 with server certificate verification; SRTP requires `res_srtp.so`, which is built with this release's Asterisk image.

Confirm:

```bash
cd phone
docker compose exec asterisk asterisk -rx 'pjsip show registrations'
docker compose exec asterisk asterisk -rx 'module show like res_srtp'
```

Registration must show `Registered`; `res_srtp.so` must be Running. Registration-only routing rejects incoming calls. After a DID is assigned, run `python3 deploy.py public-phone` from the root. Enter the DID, a fixed forwarding cellphone, admitted admin numbers, optional manual blocks and current public IPv4. US/Canada `+1` numbers are validated locally. The cellphone must be whitelisted to prevent forwarding loops.

The incoming route checks manual blocks, limits public calls to one at a time and caps a call at ten minutes. Whitelisted callers reach the assistant and must authenticate by PIN. Other callers press 5 before being forwarded to the one fixed cellphone. No arbitrary dialable destination is accepted. Calls without successful screening are rejected. Forwarding can charge both an incoming and an outgoing provider leg. Caller ID is set to the DID; the local name is `FWG NETWORK`. Carrier-displayed CNAM still requires provider provisioning and may not appear on all receiving networks.

Apply restricted UDP RTP forwarding for ports 10000–10019 to the homelab, permitting only the provider's documented media sources. Verify those sources against current VoIP.ms guidance; signaling and media addresses may differ. Start by using the registered TLS connection for signaling. Diagnose missing INVITEs before opening any inbound SIP port. Nginx Proxy Manager does not transport SIP/RTP. A public routable IPv4 is required by this setup; keep the external media/signaling address current if your ISP changes it.

## Spam rejection

`python3 deploy.py callshield` creates a host virtual environment, downloads and verifies CallShield's signed consumer list, and schedules a daily update. An indexed local SQLite lookup runs before screening/forwarding. Exact listed US/Canada numbers are rejected in BLOCK mode. Admin whitelist callers bypass CallShield; manual blocks run first.

Failed downloads retain the last valid database. A missing, invalid or over-90-day-old database falls back to ordinary screening rather than rejecting every caller. Prefix-based blocking is not implemented. Caller ID spoofing and incomplete feeds mean this cannot identify every spam call.

```bash
python3 phone/callshield/manage.py --status
python3 phone/callshield/manage.py --mode off
python3 phone/callshield/manage.py --mode block
```

Changes apply to subsequent calls. No third-party spam data is bundled in source releases. Review upstream source/data terms before redistributing a downloaded list.

## Whitelist and PIN changes

For the current implementation, whitelist and manual blocks are literal validated comparisons in `phone/config/extensions.conf`. Add another normalized `1` plus ten digits comparison in the appropriate section, retaining the order: manual blocks, concurrency limit, whitelist, CallShield, screening. Use an existing `GotoIf` as the template and run `docker compose exec asterisk asterisk -rx 'dialplan reload'` from `phone/`. Do not add a catch-all outbound route.

To change the PIN without printing it, run `python3 scripts/change_pin.py --assistant /absolute/path/to/assistant` and recreate the assistant using `docker compose up -d --force-recreate assistant` in its folder. Stop active calls first. Asterisk and the SIP password do not need changing. The PIN is hashed locally and never sent to Discord.
