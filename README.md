# DREAMEROL SYNC FORK
A Python-powered GitHub automation tool for managing multiple accounts, discovering repositories, and synchronizing Forks with their upstream sources through the GitHub API. Built for scalable, sequential synchronization, reliable repository management, and streamlined open-source workflows.




python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set GITHUB_TOKEN
python main.py
