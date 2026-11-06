# 🌙 DREAMEROL SYNC FORK

### ⚡ Automate your GitHub fork synchronization with ease.

A powerful Python CLI tool designed to discover, manage, and synchronize your GitHub forks directly with their upstream repositories.

Built for developers who want to keep their forks up to date without manually checking every repository.

✨ Simple. Fast. Safe. Automated.

---

## ✨ Features

- 🔍 Automatic Discovery — Automatically finds all forks owned by your authenticated GitHub account.
- 🔄 Upstream Synchronization — Requests synchronization through the official GitHub API.
- 👥 Multiple Accounts — Save and manage multiple GitHub accounts.
- 🔐 Secure Token Storage — Store account tokens safely using your operating system's keyring.
- 🎯 Repository Selection — Synchronize specific repositories using `--repo`.
- 🧪 Dry Run Mode — Preview synchronization without modifying repositories.
- 🛡️ Confirmation Protection — Live synchronization requires explicitly typing `SYNC`.
- 📊 Detailed Results — Clearly identifies successful syncs, conflicts, and errors.

---

## 📋 Requirements

Before getting started, make sure you have:

- 🐍 Python 3
- 🐙 A GitHub Personal Access Token with access to the repositories and permission to update them.
- 🔑 An operating-system keyring backend (required for saved accounts).

---

## 📦 Installation

1. Clone the repository

bash
git clone ⁨https://github.com/Dreamerol/DREAMEROL-SYNC-FORK.git⁩


2. Navigate into the project directory

bash
cd DREAMEROL-SYNC-FORK


3. Create a virtual environment

bash
python -m venv .venv


4. Activate the environment

🖥️ macOS / Linux:

bash
source .venv/bin/activate


🪟 Windows PowerShell:

powershell
.venv\Scripts\Activate.ps1


5. Install dependencies

bash
pip install -r requirements.txt


---

## 🔑 GitHub Authentication

Create a `.env` file in the project root and add your GitHub Personal Access Token:

dotenv
GITHUB_TOKEN=your_github_token_here


> ⚠️ Security Notice
>
> Never share your GitHub token or commit your `.env` file.
> Your `.env` file is ignored by Git.

Alternatively, you can use the built-in account manager to securely save multiple GitHub accounts.

---

## 🚀 Usage

### 🔍 Preview Synchronization

Run a dry-run to discover your forks and preview the synchronization process without making any changes.

bash
python ⁨main.py⁩ --dry-run


### 🎯 Synchronize Specific Repositories

Preview a specific repository:

bash
python ⁨main.py⁩ --dry-run --repo octocat/project-fork


Select multiple repositories:

bash
python ⁨main.py⁩ --repo octocat/project-fork --repo octocat/another-fork


You can repeat `--repo` as many times as needed.

### ⚡ Live Synchronization

Ready to synchronize?

Simply run:

bash
python ⁨main.py⁩


Or target a specific repository:

bash
python ⁨main.py⁩ --repo octocat/project-fork


🛡️ Safety First!

Before performing a live synchronization, the tool displays the selected repositories and asks for confirmation.

You must explicitly type:

text
SYNC


Any other input cancels the operation.

There is intentionally no confirmation-bypass flag.

---

## 👥 Multiple Account Management

Manage multiple GitHub accounts directly from the command line.

### ➕ Add an Account

bash
python ⁨main.py⁩ --add-account


### 📋 List Saved Accounts

bash
python ⁨main.py⁩ --list-accounts


### 🔍 Preview an Account's Forks

bash
python ⁨main.py⁩ --dry-run --account octocat


### 🔄 Synchronize an Account

bash
python ⁨main.py⁩ --account octocat


💡 Account Selection Rules

- If multiple saved accounts exist, use `--account USERNAME`.
- If `GITHUB_TOKEN` is configured, it takes priority unless `--account` is explicitly provided.
- Saved-account commands require a functioning system keyring.
- Tokens are entered without being displayed and stored through the operating-system keyring.

---

## 📊 Synchronization Results

Every repository receives a result status:

| Status | Description |
|:---|:---|
| ✅ `synced` | GitHub accepted the upstream synchronization request. |
| 🟢 `up-to-date` | No changes needed to be merged. |
| ⚠️ `conflict` | GitHub reported a synchronization conflict (HTTP 409). |
| ❌ `error` | Invalid repository data or an API request failed. |
| 🔍 `dry-run` | Repository selected for preview; no synchronization request was sent. |

> 📌 The CLI exits with a non-zero status if any repository reports `error` or `conflict`.

---

## 🧪 Running Tests

Want to verify everything works correctly?

Run the test suite:

bash
pytest


Tests use mocked GitHub API calls and a fake system keyring.

✅ No real GitHub token is required.  
✅ No actual repository synchronization occurs.

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
| `⁨main.py⁩` | CLI interface, account selection and safety prompts. |
| `⁨accounts.py⁩` | Keyring-backed account management. |
| `⁨github.py⁩` | GitHub API client and repository pagination. |
| `⁨synchronizer.py⁩` | Fork discovery, dry-run and upstream synchronization. |
| `test_accounts.py` | Account and keyring tests. |
| `test_cli.py` | CLI arguments, filters and confirmation tests. |
| `test_synchronizer.py` | Synchronization behavior tests. |

---

## 📌 Dependency Reproducibility

`requirements.txt` pins the direct dependencies.

It is not a complete transitive lockfile.

For byte-for-byte reproducible environments, generate and commit a platform-aware lockfile (for example, using `pip-compile --generate-hashes`) after resolving dependencies for the supported Python and platform combinations.

---

## 📜 License

This project is licensed under the MIT License.

See the [LICENSE](LICENSE) file for details.

---

## 💜 Credits

Developed with ❤️ by Dreamerol.

🌙 DREAMEROL SYNC FORK  
Keep your forks synchronized. Keep your workflow clean.
