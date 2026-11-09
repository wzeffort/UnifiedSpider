# AutoDL browser-assisted collector

Deploy only a local tested Git commit via `git archive <commit>` into
`/root/autodl-tmp/unifiedspider/releases/<commit>/`. Never patch cloud source.
Run that release's `bash deploy/autodl-start.sh`. AIfinance code, environment,
configuration and current services must remain unchanged.

Runtime data: `/root/autodl-tmp/unifiedspider/state/data`.
Author archives: `/root/autodl-tmp/unifiedspider/rag`.
MinerU API: loopback port 18768, existing MinerU 4.1.6 environment and model files;
separate home/config/task output directory. Two provider lanes: local and official,
one image at a time per lane, hash-based dedup. Official token belongs only in
`secrets/mineru-api-token`, permission 600, never in Git or command output.

VS Code Remote SSH target: `autodl-aifinance`. Forward remote **8889** to local
**8889**, keeping local 18765 free for the original running crawler. Install
Cookie-Editor collector 1.14.8 (or standalone 1.5.7) and open
`http://127.0.0.1:8889/` in the same local browser profile. The URL remains local
to satisfy the extension bridge's origin restrictions; no public service exposure.

Only the author-capture backend dependencies are installed by this script.
Legacy direct server crawling engines need full config/requirements.txt and browsers.
In cloud mode enter Linux export paths; native Windows directory pick/open actions
are not available. Website browsing still needs the local browser and SSH tunnel;
OCR and final exports keep running on the server after capture completes.

Local SQLite history, MinerU cache and archives are not migrated automatically.
Do not copy live SQLite files. Use SQLite backup plus a completed-task snapshot,
preserve original local files, rewrite Windows output paths in copied metadata,
and only then enable history dedup on the cloud. Do not resume both copies of a task.
