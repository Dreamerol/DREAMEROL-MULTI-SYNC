"""Secure multi-account GitHub management."""

import json

import keyring

from fork_sync.github import GitHubClient


SERVICE_NAME = "DreamerolForkSync"
ACCOUNT_INDEX = "__account_index__"


class AccountManager:
    """Manage GitHub credentials and account names in the system keyring."""

    def list_accounts(self):
        """Return the usernames registered in the keyring account index."""
        raw_accounts = keyring.get_password(SERVICE_NAME, ACCOUNT_INDEX)
        if not raw_accounts:
            return []
        try:
            accounts = json.loads(raw_accounts)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(accounts, list):
            return []
        return sorted({
            username.strip()
            for username in accounts
            if isinstance(username, str) and username.strip()
        })

    def add_account(self, token):
        """Validate a token and store it under its GitHub username."""
        if not token or not token.strip():
            raise ValueError("A non-empty GitHub token is required.")

        client = GitHubClient(token.strip())
        try:
            user = client.get_authenticated_user()
            username = user.get("login") if isinstance(user, dict) else None
            if not isinstance(username, str) or not username.strip():
                raise ValueError("GitHub did not return a valid username.")
            username = username.strip()

            keyring.set_password(SERVICE_NAME, username, token.strip())
            accounts = set(self.list_accounts())
            accounts.add(username)
            keyring.set_password(
                SERVICE_NAME,
                ACCOUNT_INDEX,
                json.dumps(sorted(accounts)),
            )
            return username
        finally:
            client.session.close()

    def get_client(self, username):
        """Create an authenticated client for a registered account."""
        if username not in self.list_accounts():
            raise ValueError(
                f"Account '{username}' is not registered. Add it with --add-account."
            )
        token = keyring.get_password(SERVICE_NAME, username)
        if not token:
            raise ValueError(f"No credentials found for '{username}'.")
        return GitHubClient(token)

    def remove_account(self, username):
        """Remove a registered account and its credentials."""
        accounts = set(self.list_accounts())
        if username not in accounts:
            raise ValueError(f"Account '{username}' is not registered.")

        keyring.delete_password(SERVICE_NAME, username)
        accounts.remove(username)
        keyring.set_password(
            SERVICE_NAME,
            ACCOUNT_INDEX,
            json.dumps(sorted(accounts)),
        )
        return True
