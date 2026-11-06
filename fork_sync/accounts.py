
"""Secure multi-account GitHub management."""

import keyring

from fork_sync.github import GitHubClient


SERVICE_NAME = "DreamerolForkSync"


class AccountManager:
    """Manage multiple GitHub accounts securely."""

    def __init__(self):
        self.accounts = {}

    def add_account(self, token):
        """Validate and securely save a GitHub account."""
        client = GitHubClient(token)

        try:
            user = client.get_authenticated_user()
            username = user["login"]

            keyring.set_password(
                SERVICE_NAME,
                username,
                token,
            )

            self.accounts[username] = username

            return username

        finally:
            client.session.close()

    def list_accounts(self):
        """Return connected account usernames."""
        return list(self.accounts.keys())

    def get_client(self, username):
        """Create an authenticated client for an account."""
        token = keyring.get_password(
            SERVICE_NAME,
            username,
        )

        if not token:
            raise ValueError(f"No credentials found for {username}.")

        return GitHubClient(token)

    def remove_account(self, username):
        """Remove an account and its saved credentials."""
        if username not in self.accounts:
            raise ValueError(f"Account not found: {username}")

        keyring.delete_password(SERVICE_NAME, username)
        del self.accounts[username]

        return True

