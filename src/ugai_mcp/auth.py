"""Authentication seam. The concrete OAuth client is deployment-specific."""


IM19_REQUIRED_SCOPES = ("im19:read",)


class AccessTokenProvider:
    """Interface for the deployment's short-lived IM19 OAuth token provider."""

    async def get_access_token(
        self,
        *,
        resource: str,
        scopes: tuple[str, ...],
    ) -> str:
        """Return a short-lived token for the exact resource and requested scopes.

        The IM19 gateway requires the im19:read scope for its read-only MCP tools.
        Implement this with the organization's approved OAuth client/secret manager.
        Never implement this by asking an LLM to construct a token.
        """
        raise NotImplementedError
