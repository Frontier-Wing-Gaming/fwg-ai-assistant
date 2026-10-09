# Local accounts

Fresh setup creates `owner`. Add a restricted user:

```bash
python3 assistant/accounts.py add admin --servers minecraft --actions status,resources,logs,restart
```

The script asks for a password locally. Server aliases must already exist in `servers.json`. `*` grants access to all configured aliases; quote it if supplying it on the shell. Power actions require confirmation and the panel API user's matching permissions.

Change an existing user's permissions without replacing their password:

```bash
python3 assistant/accounts.py grant admin --servers minecraft --actions status,resources
python3 assistant/accounts.py disable admin
```

Run the desired command, then `docker compose restart assistant` from the assistant folder. This reloads accounts and invalidates in-memory sessions. To change environment variables such as `PHONE_USER`, recreate the container instead. Web accounts are independent; admitted phone callers all use the configured `PHONE_USER` and shared PIN.
