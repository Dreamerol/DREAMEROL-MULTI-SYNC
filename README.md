# DREAMEROL SYNC FORK
A Python-powered GitHub automation tool for managing multiple accounts, discovering repositories, and synchronizing Forks with their upstream sources through the GitHub API. Built for scalable, sequential synchronization, reliable repository management, and streamlined open-source workflows.



# DREAMEROL SYNC FORK

A Python-powered GitHub automation tool for managing multiple accounts, discovering repositories, and synchronizing forks with their upstream sources through the GitHub API. Built for scalable, sequential synchronization, reliable repository management, and streamlined open-source workflows.

> Warning: This tool can merge upstream changes into your forks. Only run it against repositories and accounts you trust and intend to update.

## Features

- Authenticate to GitHub using a personal access token
- Discover repositories owned by the authenticated account
- Detect forked repositories that have an upstream parent
- Synchronize each fork with its upstream default branch
- Process forks sequentially and report status for each one
- Store account credentials securely using the system keyring
- Support multiple GitHub accounts in a structured account manager

## Tech Stack

- Python
- requests
- python-dotenv
- keyring
- pytest

## Requirements

- Python 3.9+
- A valid GitHub personal access token
- Access to the repositories you want to sync

## Setup

```bash
git clone https://github.com/Dreamerol/DREAMEROL-SYNC-FORK.git
cd DREAMEROL-SYNC-FORK

python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\Activate.ps1  # Windows PowerShell

pip install -r requirements.txt
