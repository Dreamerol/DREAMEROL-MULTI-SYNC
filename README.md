# DREAMEROL SYNC FORK

A Python command-line tool that discovers GitHub forks owned by an authenticated account and requests upstream synchronization through GitHub's API. Synchronization can update a fork's default branch, so live runs require an explicit confirmation.

## Requirements

- Python 3
- A GitHub personal access token with access to the repositories to be synchronized and permission to update them
- For saved accounts, an operating-system keyring backend

## Installation

```bash
git clone https://github.com/Dreamerol/DREAMEROL-SYNC-FORK.git
cd DREAMEROL-SYNC-FORK
python -m venv .venv
```

Activate the virtual environment, then install pinned direct dependencies:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Create `.env` in the project root and set `GITHUB_TOKEN`, or use a saved account as described below. Keep tokens secret; `.env` is ignored by Git.

```dotenv
GITHUB_TOKEN=your_github_token_here
```

## Usage

A live synchronization discovers the account's forks, displays the selected repositories, and proceeds **only if you type `SYNC`** at the prompt. Any other input cancels the run. There is intentionally no confirmation-bypass flag.

```bash
# Preview without changing repositories or requiring confirmation
python main.py --dry-run

# Preview selected fork(s)
python main.py --dry-run --repo octocat/project-fork

# Select multiple forks (repeat --repo)
python main.py --repo octocat/project-fork --repo octocat/another-fork
```

For a live run, omit `--dry-run`; review the listed repositories and type `SYNC` when prompted:

```bash
python main.py
python main.py --repo octocat/project-fork
```

Repository filters match the exact `owner/repository` name among forks belonging to the selected account. A non-matching name is an error; it is not silently ignored.

### Saved accounts

Tokens added this way are entered without echo and stored in the system keyring:

```bash
python main.py --add-account
python main.py --list-accounts
python main.py --dry-run --account octocat
python main.py --account octocat
```

When more than one saved account exists, pass `--account USERNAME`. If `GITHUB_TOKEN` is configured, it is used unless `--account` is explicitly supplied. Saved-account commands require a functioning system keyring.

## Results

- `synced`: GitHub accepted the upstream synchronization request.
- `up-to-date`: GitHub indicated no changes needed to be merged.
- `conflict`: GitHub reported a synchronization conflict (HTTP 409).
- `error`: Repository data was invalid or an API request failed.
- `dry-run`: The repository was selected for a preview; no merge request was sent.

The CLI exits non-zero if any repository reports `error` or `conflict`.

## Tests

Run the test suite with:

```bash
pytest
```

Tests use fakes for GitHub API calls and the system keyring; they do not need a real token.

## Project layout

```text
main.py                  CLI, account selection, safety prompts
fork_sync/
  accounts.py            Keyring-backed account management
  github.py              GitHub API client and repository pagination
  synchronizer.py        Fork discovery, dry-run, upstream sync
 tests/
  test_accounts.py       Account and keyring behavior
  test_cli.py            CLI arguments, filters, confirmation
  test_synchronizer.py   Fork synchronization behavior
```

## Dependency reproducibility

`requirements.txt` pins the direct dependencies. It is not a full transitive lockfile; for byte-for-byte reproducible environments, generate and commit a platform-aware lockfile (for example with `pip-compile --generate-hashes`) after resolving dependencies for the supported Python/platform matrix.

## License

MIT. See [LICENSE](LICENSE).
