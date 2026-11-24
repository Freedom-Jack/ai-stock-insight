# Single-server commissioning

**Prepared profile, pending host commissioning.** The repository supplies one foreground application under systemd, a heartbeat timer, a backup timer and an optional private notification subscriber. On Windows an isolated rehearsal started the real desk, confirmed SQLite integrity, its loopback authentication challenge and a recent scheduler pulse, terminated that process, observed the absent listener, restarted it and restored its backup to a second directory. This was a manual local restart. Systemd restart, host outage detection, private off-device delivery and off-host restoration still need evidence from the intended environment.

## Rehearse locally

```powershell
.\.venv\Scripts\python.exe -m stockinsight.server_rehearsal
.\.venv\Scripts\python.exe -m stockinsight.model_access --workspace .stockinsight
```

The first command uses a disposable empty workspace, a loopback port, a separate foreground process and a local backup. It sends no notifications or remote heartbeats. The second command exercises ordinary OS file reads with the actual Windows model process launcher. The canary database, credential marker and unrelated document contain only generated data. Run it against the directory whose inherited permissions you want to check. The regular Windows user session is required for transient AppContainer creation.

## Services and budgets

Use a supported Linux host with Python 3.11+, systemd, a dedicated nonroot `stockinsight` service user and a persistent local filesystem. Install the reviewed release under `/opt/stockinsight`, owned by the administrator. Create its virtual environment there with a system Python available outside personal home directories, and sync the locked dependencies. Keep the app bound to `127.0.0.1:8765`. Operators can use an authenticated SSH local forward to this port and the desk's native HTTP authentication. The private service log contains the session password, so restrict access to the operator and service account.

Copy the service and timer files from `ops/server_single_node/` into the target systemd unit directory. Copy the example environment files to `/etc/stockinsight/desk.env` and `/etc/stockinsight/health.env`. Keep both files root-owned, mode 0600. Provision only destinations approved for this operator. The service creates its mode-0700 state directory and checks its unprivileged identity before starting. Its writable state is under `/var/lib/stockinsight/`. Configure rotation of the private `desk.log` under the same access restrictions. [systemd service supervision](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html) · [systemd execution restrictions](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)

The supplied server unit strips hosted-model credentials and billing authorization. Its Linux research path uses service-recorded public-source methods. The verified local neural model uses Windows-specific isolation. A model-required Linux installation needs a separately verified isolated Linux executor and the corresponding receipts before commissioning that capability. The supplied profile limits the service to 150% CPU, 2 GB RAM and 96 tasks. Inspect each goal's daily investigation budget and the global 24-investigation daily ceiling before resuming. Delivery permits six automatic dispatch attempts per notice and expires unaccepted notices after seven days. The copied production workspace preserves its goal settings and existing receipts.

## Private delivery and independent health

For a server notification, provide a private, access-controlled ntfy HTTPS topic belonging to the user and a dedicated publish-only bearer credential. Set `STOCKINSIGHT_NOTIFICATION_CHANNEL=ntfy`, `STOCKINSIGHT_NTFY_URL` and `STOCKINSIGHT_NTFY_TOKEN` in `desk.env`. Establish subscriber access on the user's own endpoint. Only a generic research-ready message is sent. HTTP acknowledgement records provider acceptance. Confirm actual arrival on the intended device with the private site closed, record the time and retrieve the frozen report in the desk. No target subscription or destination was contacted during the Windows rehearsal. [ntfy publishing and access tokens](https://docs.ntfy.sh/publish/)

Set `STOCKINSIGHT_HEARTBEAT_URL` in `health.env` to a private success-ping URL on an independent observer. The health timer checks the actual loopback authentication challenge, SQLite integrity and foreground-scheduler pulse before posting an empty HTTPS body. Configure the external observer for a two-minute cadence with an alert after three consecutive misses. Its alert destination must reach the operator even when the research host is down. Record a real alert and its recovery by stopping the service, then separately interrupting the host. Preserve the observer's timestamps. [Success ping protocol](https://healthchecks.io/docs/http_api/)

## Backup and single-owner handover

Provision an access-controlled backup volume mounted at `/mnt/stockinsight-backup` and writable by the service user. The timer makes one verified snapshot daily and catches up once after a missed run. It checks that the configured path is a real mount. A mount alone provides no evidence of off-host protection. Arrange authorized encrypted off-host replication and retention, then restore one actual off-host copy to a separate machine or location and verify SQL, document hashes, expected-run histories and pending delivery records. Local backup never prunes prior snapshots.

Before enabling the new scheduler, stop the old desk and verify that its process exited. Record outstanding jobs, missed deadlines, pending delivery and any indeterminate notification attempts. Transfer the final verified backup by an authorized private route. Restore it into `/var/lib/stockinsight/workspace` under the dedicated service identity. Keep the former workspace offline. Rebind watchlist ingestion to manual server-side import or a separately approved supported source. Keep its source timestamp and freshness separate from server uptime. Confirm the same report identifiers and outstanding notices are present on the new workspace.

On the target, verify the assembled units and identity before enabling any scheduler.

```sh
systemd-analyze verify /etc/systemd/system/stockinsight*.service /etc/systemd/system/stockinsight*.timer
systemctl daemon-reload
systemctl enable --now stockinsight.service
systemctl enable --now stockinsight-health.timer stockinsight-backup.timer
systemctl list-timers 'stockinsight*'
systemctl show stockinsight.service -p MainPID -p Restart -p User
```

After the old owner is offline, exercise one actual restart after a process crash, one host outage, one successful externally observed heartbeat, one subscriber delivery and one off-host restore. Match a report ID across dispatch, evidence, backup and notification. Confirm the restored credentials are supplied separately on the destination. Continuous operation remains pending until the operator records these target-specific results.
