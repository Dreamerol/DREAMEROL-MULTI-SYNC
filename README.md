




<h1 align="center">🛠️ 𝗗𝗥𝗘𝗔𝗠𝗘𝗥𝗢𝗟 𝗦𝗬𝗡𝗖 𝗙𝗢𝗥𝗞</h1>



<p align="center">
  <strong>Automated GitHub Fork Synchronization Tool</strong>
</p>

<p align="center">
  A Python command-line tool that discovers forks owned by the authenticated
  GitHub account and requests upstream synchronization through the GitHub API.
  Forks are processed sequentially, with individual results reported for each repository.
</p>

> ⚠️ **Warning:** Synchronizing a fork can modify its default branch by merging upstream changes.
> Review the repositories accessible to your token before running the tool.
> Synchronization conflicts are reported but are not automatically resolved.

## 🚀 Features

- 🔐 **GitHub Authentication** — Authenticates through the GitHub API using `GITHUB_TOKEN`.
- 🔎 **Automatic Discovery** — Finds repositories owned by the authenticated account.
- 📄 **Pagination Support** — Retrieves repository listings across multiple API pages.
- 🍴 **Fork Detection** — Identifies forks using GitHub repository metadata.
- 🔄 **Upstream Synchronization** — Requests upstream merges into each fork's default branch.
- 📊 **Individual Reporting** — Provides a synchronization result for every repository.
- ⚠️ **Error Handling** — Reports conflicts, API failures, and repository-related errors.

The repository also includes an `AccountManager` helper that validates accounts and stores tokens using the system keyring. This functionality is not yet integrated into the `⁨main.py⁩` command-line workflow, which currently uses a single `GITHUB_TOKEN`.

## 📋 Requirements

- Python 3
- A GitHub personal access token with sufficient repository access and permissions to perform upstream synchronization.

## ⚙️ Installation

Clone the repository and navigate to the project directory:

bash
git clone ⁨https://github.com/Dreamerol/DREAMEROL-SYNC-FORK.git⁩

cd DREAMEROL-SYNC-FORK

Create a virtual environment:
bash
python -m venv .venv

Activate the virtual environment:
bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

Install the required dependencies:
bash
pip install -r requirements.txt
```

## 🔐 Configuration

Create a `.env` file in the project root or copy the provided `.env.example` file.

Add your GitHub personal access token:

dotenv
GITHUB_TOKEN=your_github_token_here


> 🔒 Security: Keep your access token private. Never commit your `.env` file or expose your credentials in public repositories.

Use only the repository access and permissions required by the tool.

## ▶️ Usage

Once the virtual environment is activated and your `.env` file is configured, run:

bash
python ⁨main.py⁩


The program:

Authenticates with GitHub.
Identifies the authenticated account.
Discovers the account's accessible forks.
Requests upstream synchronization for each fork.
Reports the result of every synchronization attempt.

If `GITHUB_TOKEN` is missing, the application displays a configuration error and exits.

## 📊 Result Statuses

Each repository receives an individual synchronization status:

| Status | Description |
|:---|:---|
| ✅ `synced` | GitHub accepted the upstream synchronization request. |
| ℹ️ `up-to-date` | The fork is already synchronized with its upstream repository. |
| ⚠️ `conflict` | GitHub reported a synchronization conflict (HTTP 409). |
| ❌ `error` | Repository data was invalid or the API request failed. |

A failure affecting one repository is reported individually. The synchronizer continues processing the remaining forks.

## 📁 Project Structure

text
DREAMEROL-SYNC-FORK/
│
├── ⁨main.py⁩                  # CLI entry point
│
├── fork_sync/
│   ├── ⁨accounts.py⁩          # Keyring-backed account helper
│   ├── ⁨github.py⁩            # GitHub API client
│   └── ⁨synchronizer.py⁩      # Fork discovery and synchronization
│
├── tests/
│   └── test_synchronizer.py # Test module (not yet implemented)
│
├── .env.example             # Token configuration example
├── requirements.txt         # Python dependencies
└── LICENSE                  # Project license


## 🧪 Development Status

The project is under active development.

- The core fork discovery and synchronization workflow is implemented.
- The `AccountManager` helper is available but not yet integrated into the CLI.
- `tests/test_synchronizer.py` is currently empty.
- `pytest` is included as a dependency, but automated synchronizer tests have not yet been implemented.

## 🗺️ Potential Improvements

- Integrate `AccountManager` into the CLI workflow.
- Implement automated synchronizer tests.
- Add repository selection and exclusion options.
- Introduce a dry-run mode.
- Improve synchronization reporting.

## 📜 License

See [LICENSE](LICENSE) for details.
