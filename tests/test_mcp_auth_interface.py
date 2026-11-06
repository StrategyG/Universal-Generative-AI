import pytest

from ugai_mcp.auth import AccessTokenProvider, IM19_REQUIRED_SCOPES


@pytest.mark.asyncio
async def test_unconfigured_mcp_token_provider_does_not_issue_a_fake_token():
    with pytest.raises(NotImplementedError):
        await AccessTokenProvider().get_access_token(
            resource="https://im19.example.test",
            scopes=IM19_REQUIRED_SCOPES,
        )
