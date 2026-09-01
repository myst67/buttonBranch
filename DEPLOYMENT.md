# Deploying on your own machine, from scratch

Everything below was run end to end on a clean checkout. Where a command is
platform-specific, the Linux/macOS form is given first and the Windows
(PowerShell) form second.

Verified on Linux with Python 3.11.15 and Node 26.8.1. The Windows commands are
the platform equivalents of those same steps - **on Windows 11, follow the
[appendix](#appendix-windows-11-step-by-step)**, which spells the whole thing
out from an empty machine.

---

## 1. What you are installing

Two pieces:

| Piece | What it is | Port |
|---|---|---|
| **Backend** | Python: FastAPI + scikit-learn + OR-Tools. Parses the sheet, trains, solves, exports. | 8000 |
| **UI** | Angular. Upload, model panel, roster grid, download. | 4200 (dev only) |

There are two ways to run them, and you probably want the second:

* **Development** - two processes. Angular's dev server on `:4200` proxies
  `/api` to the backend on `:8000`. Live reload while editing.
* **Local deployment** - one process. You build the UI once, and the backend
  serves it. Everything on `http://localhost:8000`. Nothing else to keep alive.

## 2. Prerequisites

| Need | Version | Check with |
|---|---|---|
| Python | 3.10 or newer (tested 3.11) | `python3 --version` |
| Node.js | 22.22.3+, 24.15+, or 26+ (tested 26.8.1) | `node --version` |
| npm | comes with Node (tested 10) | `npm --version` |
| Git | any | `git --version` |

On Windows install Python from python.org (tick **Add python.exe to PATH**) and
Node from nodejs.org. Nothing else is required - no database, no Docker, and no
internet access once installed.

Disk: about 1.4 GB, nearly all of it `node_modules` and the OR-Tools wheel.

## 3. Get the code

```bash
git clone https://github.com/myst67/buttonBranch.git
cd buttonBranch
git checkout claude/monthly-roster-scheduler-zloqyg
```

## 4. Backend

### 4.1 Create the virtual environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
```

PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r backend\requirements.txt
```

> If PowerShell refuses to run the activate script, allow it for your user once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

The install pulls in FastAPI, uvicorn, pandas, openpyxl, scikit-learn, joblib
and OR-Tools. Add `-r backend/requirements-dev.txt` instead if you also want to
run the tests.

### 4.2 Make a sample sheet to upload

The repo ships a seed team (60 employees over 20 clients) but no roster. Build
one so you have something to feed the app on day one:

```bash
cd backend
python scripts/generate_sample_history.py
cd ..
```

That writes `backend/data/sample/last-month-2025-06.xlsx`. Skip this if you are
uploading your own sheet straight away.

### 4.3 Start it

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check it in another terminal:

```bash
curl http://localhost:8000/api/health
# {"status":"ok","history_months":0}
```

Interactive API docs are at <http://localhost:8000/docs>.

Use `--host 0.0.0.0` only if you want other machines on your network to reach
it. There is no authentication, so keep it on `127.0.0.1` unless you have a
reason not to.

## 5. UI

### 5.1 Install

```bash
npm install
```

This takes a few minutes and prints audit warnings about the Angular 6
toolchain. They are expected on a project of this vintage and do not affect the
build.

### 5.2 Nothing else to configure

The UI is Angular 22, built with esbuild. There is no `NODE_OPTIONS` workaround
and no browser needed for the tests - if `npm install` finished, `npm run build`
and `npm start` will work.

## 6. Run it

### Option A - local deployment (one process, recommended)

Build the UI once, then let the backend serve it:

```bash
npm run build                    # writes dist/button-app/browser
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **<http://localhost:8000>**. The backend serves the built UI at `/` and the
API under `/api`, so there is only one process to keep running and no CORS or
proxy to configure.

Rebuild (`npm run build`) after any change to `src/`; restart uvicorn
after any change to `backend/`.

> Start uvicorn **after** the build finishes. It looks for `dist/button-app/browser`
> once, at startup - a backend started while the build had the folder wiped will
> answer `/api` normally but return 404 for the page.

### Option B - development (two processes)

Terminal 1:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Terminal 2:

```bash
npm start                        # ng serve, with proxy.conf.json
```

Open **<http://localhost:4200>**. `proxy.conf.json` forwards `/api` to
`:8000`, and both sides reload on save.

## 7. First run

1. Open the app.
2. **Step 1** - drop in `backend/data/sample/last-month-2025-06.xlsx` (or your
   own last-month sheet). It should read 60 employees over 20 clients and offer
   to build the next month.
3. **Step 2** - shows what the model has learned. On the first upload the shift
   model sits at 0% weight: one month contains no shift *change* to learn from,
   so the transparent heuristics do the work. It starts training on your second
   upload.
4. **Step 3** - press **Generate roster**. A few seconds for 60 people.
5. **Step 4** - check the green validation banner, then **Download Excel**.

Next month, upload the sheet you exported. That is the whole loop.

## 8. Keeping it running

### Linux - systemd user service

`~/.config/systemd/user/roster.service`:

```ini
[Unit]
Description=Monthly roster builder
After=network.target

[Service]
WorkingDirectory=/home/YOU/buttonBranch/backend
Environment=ROSTER_DATA_DIR=/home/YOU/roster-data
ExecStart=/home/YOU/buttonBranch/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now roster
systemctl --user status roster
journalctl --user -u roster -f      # logs
```

### macOS - launchd

Save as `~/Library/LaunchAgents/com.roster.plist`, with `ProgramArguments` set to
the same uvicorn path and `WorkingDirectory` to `backend`, then
`launchctl load ~/Library/LaunchAgents/com.roster.plist`.

### Windows - Task Scheduler

Create a task that runs at logon:

* Program: `C:\path\to\buttonBranch\.venv\Scripts\uvicorn.exe`
* Arguments: `app.main:app --host 127.0.0.1 --port 8000`
* Start in: `C:\path\to\buttonBranch\backend`

## 9. Configuration

Both are read at startup, so restart after changing them.

| Variable | Default | What it does |
|---|---|---|
| `ROSTER_DATA_DIR` | `backend/data` | Where uploaded history, the trained model and generated workbooks are written. Point it outside the repo to keep your data across re-clones. |
| `ROSTER_CORS_ORIGINS` | `http://localhost:4200,http://127.0.0.1:4200` | Browser origins allowed to call the API. Only relevant in development - in Option A the UI is same-origin. |

```bash
ROSTER_DATA_DIR=~/roster-data uvicorn app.main:app --port 8000
```

Other knobs live in the UI's **Build the month** row (target month, seed, minimum
people per client and shift, shift-balance slack, time limit); the scheduling
rules themselves are in `backend/app/config.py`.

## 10. Your data

Under `ROSTER_DATA_DIR` (by default `backend/data`):

| Path | Contents | Keep? |
|---|---|---|
| `history/<YYYY-MM>.json` | every roster you have uploaded - the training set | **yes, back this up** |
| `models/roster_model.joblib` | the trained model | no, rebuilt from history |
| `exports/` | every workbook generated | no |
| `seed/team.json` | the starting team, in git | in git |
| `sample/` | the generated sample sheet | no |

* **Back up** `history/` - it is small JSON and everything else is derived from it.
* **Start over**: delete `history/` and `models/`, then restart.
* **Retrain by hand** (never normally needed - uploads do it):
  `curl -X POST http://localhost:8000/api/train`
* **Change the team size**: `python backend/scripts/build_seed_team.py --clients 30`
  recalculates the headcount and rewrites the seed.

## 11. Verify the install

```bash
pip install -r backend/requirements-dev.txt
cd backend && pytest -q                  # 37 passed

cd ..
npm test                                 # 5 passed
```

The UI tests run on Vitest with jsdom - no browser or display needed.

Or smoke-test the running server:

```bash
curl -F "file=@backend/data/sample/last-month-2025-06.xlsx" \
     http://localhost:8000/api/history/upload
curl -X POST http://localhost:8000/api/roster/generate \
     -H 'Content-Type: application/json' -d '{}'
```

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `npm warn EBADENGINE Unsupported engine` | your Node is older than the supported range | install Node 22.22.3+, 24.15+ or 26+ |
| UI loads but every panel is empty; console shows failed `/api` calls | backend not running, or on another port | start uvicorn on 8000; in dev check `proxy.conf.json` |
| "The backend is not reachable" banner | same | as above |
| `Address already in use` | port taken | `uvicorn ... --port 8001`, and update `proxy.conf.json` to match |
| `ModuleNotFoundError: No module named 'app'` | uvicorn started from the wrong directory | run it from `backend/` |
| `ModuleNotFoundError: No module named 'fastapi'` | virtualenv not activated | `source .venv/bin/activate` |
| Upload fails: "No employee-name column found" | the sheet has no Name/Employee column, or the header row was not found | give the column a header like `Name`; keep any title row above it |
| Upload warns "week-offs were irregular" | last month's offs were not a clean repeating block | informational; the closest block was used |
| Generate returns 422 with reasons | the team cannot satisfy the rules | read the reason - usually a client with fewer than 8 people |
| Generate is slow | it is optimising | lower **Time limit (s)** in the UI; the first phase is done in well under a second |
| `ng` not found | dependencies not installed | `npm install` (use `npx ng` rather than a global install) |
| `/api` answers but `http://localhost:8000/` returns 404 | backend started before `dist/button-app` existed | build first, then restart uvicorn (section 6) |
| `Address already in use` on 8000 after a restart | the previous backend is still running | stop it first: `pkill -f "uvicorn app.main"`, or Task Manager on Windows |

## 13. Updating

```bash
git pull
pip install -r backend/requirements.txt      # if requirements changed
npm install                                  # if package.json changed
npm run build                                # Option A only
# restart uvicorn
```

Your uploaded history is untouched by an update; the model refits from it on the
next upload, or immediately via `POST /api/train`.

---

## Appendix: Windows 11, step by step

The whole thing in one pass, assuming nothing is installed yet. Written out in
full rather than as differences from the Linux commands.

### A. Install the three prerequisites

1. **Python** - <https://www.python.org/downloads/> . On the first installer
   screen tick **"Add python.exe to PATH"** before pressing Install. Missing
   that box is the single most common cause of `py is not recognized` later.
2. **Node.js** - <https://nodejs.org/> , the current or LTS build. Anything from
   22.22.3 upwards works, including Node 26. Accept the installer defaults.
3. **Git** - <https://git-scm.com/download/win> . Accept the defaults.

Close any terminal you already had open afterwards - a terminal only picks up
newly installed programs when it starts.

### B. Open PowerShell

Press **Start**, type `PowerShell`, and open **Windows PowerShell**. Check all
three installs answer:

```powershell
py --version        # Python 3.11.x  (3.10 or newer)
node --version      # v22.22.3+, v24.15+ or v26+
git --version       # git version 2.x
```

If any says *"not recognized"*, that program is not installed or PATH was
missed - reinstall it, then open a fresh PowerShell window.

### C. Get the code

```powershell
cd $HOME
git clone https://github.com/myst67/buttonBranch.git
cd buttonBranch
```

Everything below is run from this `buttonBranch` folder.

### D. Set up the Python side

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

After the second line your prompt gains a `(.venv)` prefix:

```
(.venv) PS C:\Users\you\buttonBranch>
```

That prefix means the project's Python is active. If PowerShell refuses with
*"running scripts is disabled on this system"*, allow it once for your user and
run the activate line again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned      # answer Y
```

### E. Make a sample roster to upload

```powershell
cd backend
python scripts\generate_sample_history.py
cd ..
```

Writes `backend\data\sample\last-month-2025-06.xlsx`. Skip it if you are
uploading your own sheet.

### F. Build the UI

```powershell
npm install
npm run build
```

`npm install` takes a couple of minutes; the build takes a few seconds.

### G. Run it

```powershell
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave that window open - it is the running application. Open
**<http://localhost:8000>** in your browser.

Press **Ctrl+C** in the PowerShell window to stop it.

### H. Every time after the first

Nothing above needs repeating. To start it again:

```powershell
cd $HOME\buttonBranch
.\.venv\Scripts\Activate.ps1
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Only re-run `npm run build` after changing anything in `src\`, and
`pip install -r backend\requirements.txt` after a `git pull` that changed the
requirements.

### I. Windows-specific problems

| Message | Fix |
|---|---|
| `py : The term 'py' is not recognized` | Python not installed, or "Add to PATH" was missed. Reinstall, then open a new PowerShell. Or try `python -m venv .venv`. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer `Y`, then run the activate line again. |
| `npm : The term 'npm' is not recognized` | Node not installed, or the terminal predates the install. Open a new PowerShell. |
| `ModuleNotFoundError: No module named 'fastapi'` | The `(.venv)` prefix is missing - run the activate line. |
| `ModuleNotFoundError: No module named 'app'` | You are not in the `backend` folder. `cd backend` first. |
| `[Errno 10048] ... address already in use` | An older copy is still running. Close its window, or use `--port 8001`. |
| Browser shows "can't reach this page" | The PowerShell window running uvicorn was closed. It has to stay open. |
| Page loads but panels are empty | Backend up but UI not built - run `npm run build`, then restart uvicorn. |
