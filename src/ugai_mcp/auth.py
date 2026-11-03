"""Authentication seam. The concrete OAuth client is deployment-specific."""

from __future__ import annotations

from typing import Protocol


class AccessTokenProvider(Protocol):
    async def get_access_token(self, *, resource: str) -> str:
        """Return a short-lived access token for the exact IM19 resource audience.

        Implement this with the organization's approved OAuth client/secret manager.
        Never implement this by asking an LLM to construct a token.
        """
