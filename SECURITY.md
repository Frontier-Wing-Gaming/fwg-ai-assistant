# Security and privacy

Operational actions are deterministic application routes, not tools granted to the language model. Each action requires a user/server permission and a one-use confirmation bound to its session, server and action, with a short expiry. The application does not execute shell requests or arbitrary console commands. Panel console redaction is best effort; logs can still contain private information.

Use a dedicated restricted Pterodactyl Client API account. Keep Ollama and the phone bridge private. Serve the web interface over HTTPS with the exact configured origin. Limit LAN SIP with its network ACL and your host firewall. Do not expose Docker sockets, AMI, ARI or management endpoints publicly.

Phone whitelist admission is combined with a PIN because caller ID can be spoofed. It does not prove a caller's real identity. The current implementation shares one phone account/PIN across the whitelist. PIN attempts and call duration are limited. No arbitrary paid outbound dial API is exposed.

Configuration is generated locally and ignored by Git. Password/PIN hashes, panel API keys, SIP passwords, Discord webhooks, caller numbers, routing files, logs, databases, voice models and rollback snapshots are sensitive even when a value is hashed. Keep the assistant directory restricted to its owner and take encrypted private backups separately. Web users.json is readable by the container UID but its parent directory should remain private. Never force-add ignored files to Git.

Speech and language inference run locally after model downloads. External requests include Pterodactyl API calls, initial model downloads, optional signed spam-feed updates, provider telephone traffic and Discord webhook notifications. The monitor sends container/website/game names, health details and host usage to Discord. Asterisk logs can contain telephone numbers. The application audit includes usernames, actions and server aliases. Do not upload runtime logs or SIP packet captures without careful redaction; SRTP negotiation captures can contain sensitive keys.

Rotate any credential or webhook that has been disclosed before sharing a release. Removing a secret from the current files does not remove it from Git history. This project is prepared from an explicit source allowlist with a fresh history; deployment directories must not be imported wholesale.

Report suspected vulnerabilities privately to the repository owner through GitHub private vulnerability reporting when enabled, or request a private contact without posting exploit credentials in an issue. No automated scanner proves the absence of every secret or vulnerability.
