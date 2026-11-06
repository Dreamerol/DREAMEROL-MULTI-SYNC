<h1 align="center">🛠️ DREAMEROL SYNC FORK</h1>

<h2 align="center">
  <strong>Automated GitHub fork synchronization</strong>
</h2>




https://raw.githubusercontent.com/Dreamerol/Dreamerol/main/Mihaela%20Koseva%20Sync.png





<div align="center">

<a href="https://github.com/Dreamerol/CARDFOLIO">

<img
src="https://raw.githubusercontent.com/Dreamerol/Dreamerol/main/mihaela%20koseva-PYTHON-22.jpg"
width="100%"
alt="Mihaela Koseva (Михаела Косева) • Sofia University (Софийски университет) • SMG (СМГ) • Sofia • GitHub: Dreamerol • github.com/Dreamerol • LinkedIn: Mihaela Koseva • Software Engineering • AI Engineer • Applied Machine Learning • Data Science • Python • C++ • Java • SQL • Mihaela Koseva (Михаела Косева)"
/>

</a>

</div>




<p align="center">
  A Python command-line tool that finds forks owned by the authenticated GitHub account
  and requests upstream synchronization through the GitHub API.
</p>

> ⚠️ **Warning:** Synchronizing a fork can modify its default branch by merging upstream changes. Review the repositories accessible to your token before running the tool. Conflicts are reported but are not automatically resolved.

## Features

- Authenticates with GitHub using a personal access token stored in `GITHUB_TOKEN`.
- Lists repositories owned by the authenticated account, including paginated results.
- Finds repositories GitHub identifies as forks with parent metadata.
- Requests an upstream merge into each fork's default branch.
- Processes forks sequentially and reports a result for each one.
- Handles synchronization conflicts and reports API or repository-data errors.

> **Multi-account helper:** `fork_sync/accounts.py` provides an `AccountManager` that validates accounts and stores tokens with the system keyring. It is not currently connected to the CLI; `main.py` uses one `GITHUB_TOKEN`.

## Requirements

- Python 3
- A GitHub personal access token with access to the repositories you want to synchronize and permission to perform upstream merges

## Installation

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

## Configuration

Create a `.env` file in the project root (or copy `.env.example`) and add your token:

```dotenv
GITHUB_TOKEN=your_github_token_here
```

Keep your token private. Do not commit `.env` or expose credentials in a public repository. Use only the repository access and permissions needed for your use case.

## Usage

With the virtual environment activated and `.env` configured, run:

```bash
python main.py
```

The program authenticates with GitHub, prints the authenticated account, discovers its forks, requests synchronization for each fork, and reports the result. If `GITHUB_TOKEN` is missing, it prints a configuration error and exits.

## Result statuses

| Status | Meaning |
|:---|:---|
| `synced` | GitHub accepted the upstream synchronization request. |
| `up-to-date` | GitHub returned no merge result, so no changes needed to be merged. |
| `conflict` | GitHub reported a synchronization conflict (HTTP 409). Resolve it separately. |
| `error` | Repository data was invalid or the API request failed. |

Errors handled by the synchronizer are reported for the affected repository, and processing continues with the remaining forks.

## Project structure

```text
DREAMEROL-SYNC-FORK/
├── main.py                  # CLI entry point
├── fork_sync/
│   ├── __init__.py          # Package marker
│   ├── accounts.py          # Keyring-backed account helper
│   ├── github.py            # GitHub API client
│   └── synchronizer.py      # Fork discovery and synchronization
├── tests/
│   └── test_synchronizer.py # Test module (currently empty)
├── .env.example             # Token configuration example
├── requirements.txt         # Python dependencies
└── LICENSE                  # Project license
```

## Development status

The fork discovery and synchronization flow is implemented. The account helper is not yet integrated into the CLI, and `tests/test_synchronizer.py` is currently empty; automated synchronizer tests have not been implemented.

## License

See [LICENSE](LICENSE) for details.
