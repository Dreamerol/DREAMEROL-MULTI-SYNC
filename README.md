# 🌙 DREAMEROL SYNC FORK

### ⚡ Keep your GitHub forks synchronized effortlessly.

A Python command-line tool that automatically discovers GitHub forks owned by an authenticated account and requests upstream synchronization through the official GitHub API.

Designed to make fork management easier, faster and more convenient.

> 💜 Simple workflow. Secure authentication. Reliable synchronization.

---

## ✨ Requirements

Before getting started, make sure you have:

- 🐍 **Python 3**
- 🔑 **GitHub Personal Access Token** with access to the repositories being synchronized and permission to update them.
- 🔐 **Operating-system keyring backend** (required for saved accounts).

---

## 📦 Installation

### 1. Clone the repository

bash
git clone ⁨https://github.com/Dreamerol/DREAMEROL-SYNC-FORK.git⁩
cd DREAMEROL-SYNC-FORK
```

### 2. Create a virtual environment

bash
python -m venv .venv


### 3. Activate the environment

🐧 macOS / Linux

bash
source .venv/bin/activate


🪟 Windows PowerShell

powershell
.venv\Scripts\Activate.ps1


### 4. Install dependencies

bash
pip install -r requirements.txt


---

## 🔑 GitHub Authentication

Create a `.env` file in the project root and configure your GitHub token.

dotenv
GITHUB_TOKEN=your_github_token_here


You can also use the built-in saved account manager described below.

> ⚠️ Security Notice
>
> Keep your GitHub tokens private.
> Never share your credentials or commit your `.env` file.
> The `.env` file is ignored by Git.

---

## 🚀 Usage

DREAMEROL SYNC FORK provides two synchronization modes:

- 🔍 Dry Run — Preview selected repositories without making changes.
- ⚡ Live Sync — Request actual upstream synchronization through GitHub.

### 🔍 Preview Synchronization

Preview all discovered forks without changing repositories or requiring confirmation.

bash
python ⁨main.py⁩ --dry-run


### 🎯 Preview Specific Repositories

Preview a selected fork:

bash
python ⁨main.py⁩ --dry-run --repo octocat/project-fork


Select multiple forks by repeating `--repo`:

bash
python ⁨main.py⁩ --repo octocat/project-fork --repo octocat/another-fork


### ⚡ Live Synchronization

To perform an actual synchronization, simply omit `--dry-run`.

bash
python ⁨main.py⁩


Or synchronize a specific repository:

bash
python ⁨main.py⁩ --repo octocat/project-fork


### 🛡️ Safety Confirmation

Live synchronization can update a fork's default branch.

For this reason, the application requires explicit confirmation before proceeding.

The tool displays the selected repositories and asks you to type:

text
SYNC


Only the exact confirmation `SYNC` allows the operation to continue.

Any other input cancels the run.

> 🔒 There is intentionally no confirmation-bypass flag.

### 🎯 Repository Filters

Repository filters match the exact `owner/repository` name among forks belonging to the selected account.

A repository that does not match is reported as an error rather than silently ignored.

---

## 👥 Saved Accounts

Manage multiple GitHub accounts without manually configuring your token every time.

Tokens are entered without echo and securely stored using your operating system's keyring.

### ➕ Add an Account

bash
python ⁨main.py⁩ --add-account


### 📋 List Saved Accounts

bash
python ⁨main.py⁩ --list-accounts


### 🔍 Preview Account Repositories

bash
python ⁨main.py⁩ --dry-run --account octocat


### ⚡ Synchronize an Account

bash
python ⁨main.py⁩ --account octocat


### 💡 Account Selection

- Multiple saved accounts require `--account USERNAME`.
- If `GITHUB_TOKEN` is configured, it is used unless `--account` is explicitly supplied.
- Saved-account commands require a functioning operating-system keyring.

---

## 📊 Synchronization Results

Each repository receives a status describing the synchronization result.

| Status | Description |
|:---|:---|
| ✅ `synced` | GitHub accepted the upstream synchronization request. |
| 🟢 `up-to-date` | GitHub indicated that no changes needed to be merged. |
| ⚠️ `conflict` | GitHub reported a synchronization conflict (HTTP 409). |
| ❌ `error` | Repository data was invalid or an API request failed. |
| 🔍 `dry-run` | Repository was selected for preview; no synchronization request was sent. |

> 📌 Exit Status
>
> The CLI exits with a non-zero status if any repository reports `error` or `conflict`.

---

## 🧪 Tests

Run the test suite to verify the application's behavior.

bash
pytest


The tests use fakes for GitHub API calls and the system keyring.

- ✅ No real GitHub token required.
- ✅ No actual repository synchronization.
- ✅ Safe testing environment.

---

## 📁 Project Structure

text
DREAMEROL-SYNC-FORK/
│
├── ⁨main.py⁩
│
├── fork_sync/
│   ├── ⁨accounts.py⁩
│   ├── ⁨github.py⁩
│   └── ⁨synchronizer.py⁩
│
├── tests/
│   ├── test_accounts.py
│   ├── test_cli.py
│   └── test_synchronizer.py
│
├── requirements.txt
├── LICENSE
└── ⁨readme.md⁩


### 🧩 Core Components

| File | Description |
|:---|:---|
| `⁨main.py⁩` | CLI, account selection and safety prompts. |
| `⁨accounts.py⁩` | Keyring-backed account management. |
| `⁨github.py⁩` | GitHub API client and repository pagination. |
| `⁨synchronizer.py⁩` | Fork discovery, dry-run and upstream synchronization. |
| `test_accounts.py` | Account and keyring behavior tests. |
| `test_cli.py` | CLI arguments, filters and confirmation tests. |
| `test_synchronizer.py` | Fork synchronization behavior tests. |

---

## 📌 Dependency Reproducibility

`requirements.txt` pins the direct dependencies.

It is not a complete transitive lockfile.

For byte-for-byte reproducible environments, generate and commit a platform-aware lockfile (for example, using `pip-compile --generate-hashes`) after resolving dependencies for the supported Python and platform matrix.

---

## 📜 License

This project is licensed under the MIT License.

See the [LICENSE](LICENSE) file for details.

---

## 💜 DREAMEROL

Made with ❤️ by Dreamerol.

🌙 DREAMEROL SYNC FORK

Synchronize your forks. Simplify your workflow.

⭐ If you find this project useful, consider giving it a star!

![GitHub
