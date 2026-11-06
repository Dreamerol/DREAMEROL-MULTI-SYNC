# DREAMEROL SYNC FORK

A Python command-line tool that discovers forks owned by the authenticated GitHub account and asks GitHub to merge each fork’s upstream branch into its default branch. Forks are processed sequentially, with a result reported for each repository.

> **Warning:** Synchronizing a fork can change its contents by merging upstream changes. Check the account and repositories selected by your token before running the tool.

## What it does

- Authenticates with the GitHub API using `GITHUB_TOKEN`.
- Lists repositories owned by the authenticated account, including paginated results.
- Selects repositories identified by GitHub as forks with parent metadata.
- Requests an upstream merge using each fork’s default branch.
- Reports successful syncs, forks already up to date, conflicts, and errors.

The repository also includes an `AccountManager` helper that validates accounts and stores tokens using the system keyring. It is not currently connected to the `main.py` command-line flow, which uses one `GITHUB_TOKEN`.

## Requirements

- Python 3
- A GitHub personal access token that can access the repositories you want to synchronize and perform the requested upstream merges

## Setup

Clone the repository and install its dependencies:

```bash
git clone https://github.com/Dreamerol/DREAMEROL-SYNC-FORK.git
cd DREAMEROL-SYNC-FORK

python -m venv .venv
```

Activate the virtual environment:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configure

Create a `.env` file in the project root (or copy `.env.example`) and set your token:

```dotenv
GITHUB_TOKEN=your_github_token_here
```

Keep this token private and do not commit your `.env` file.

## Run

With the virtual environment active and `.env` configured, run:

```bash
python main.py
```

The program prints the authenticated account, the number of forks found, and a status for each synchronization attempt. If `GITHUB_TOKEN` is not set, it prints a configuration error and exits.

## Result statuses

- `synced` — GitHub accepted the upstream merge request.
- `up-to-date` — GitHub indicated that no merge was needed.
- `conflict` — GitHub reported a synchronization conflict (HTTP 409); the conflict must be handled separately.
- `error` — repository data was invalid or the API request failed. An error message is included when available.

A failure for one fork is returned as that fork’s result; the synchronizer continues with the remaining forks.

## Project layout

```text
.
├── main.py                  # CLI entry point
├── fork_sync/
│   ├── accounts.py          # Keyring-backed account helper
│   ├── github.py            # GitHub API client
│   └── synchronizer.py      # Fork discovery and synchronization
├── tests/
│   └── test_synchronizer.py # Test module (tests not implemented yet)
├── .env.example             # Token configuration example
└── requirements.txt         # Python dependencies
```

## Development status

`tests/test_synchronizer.py` is currently empty, so the repository does not yet have automated synchronizer tests. The project includes `pytest` as a dependency, but there are no implemented tests to run at this time.

## License

See [LICENSE](LICENSE).
