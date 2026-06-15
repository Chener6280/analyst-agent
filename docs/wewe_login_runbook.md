# WeWe RSS Login Runbook

The production WeChat path uses local `wewe-rss` plus `dajiala` through
`ir_search`. Before live retrieval, the MVP pipeline now prepares `wewe-rss`
automatically when `--retrieval-profile live` and `wechat_opencli` are used.

Local defaults:

- service: `http://localhost:4001/dash`
- auth code: `irsearch`
- Colima runtime: `colima`
- Docker container: `wewe-rss-ir`
- feed/account map: `/Users/chen/Documents/ir_search/accounts.json`

What happens at pipeline start:

1. `scripts/prepare_wewe_login.py` checks/starts Colima.
2. It starts Docker container `wewe-rss-ir`.
3. It probes `http://localhost:4001/dash`.
4. It calls `feed.refreshArticles` on one configured feed.
5. If WeRead token is expired, it opens the dash page and exits with
   `wewe_login_needed=true`.

When login is required:

1. Open `http://localhost:4001/dash`.
2. Enter auth code `irsearch` if prompted.
3. Scan the WeRead login QR code with WeChat.
4. Rerun the pipeline after login succeeds.

Escape hatch for unattended or cache-only runs:

```bash
python3 scripts/run_mvp_pipeline.py ... --skip-wewe-login-prepare
```

