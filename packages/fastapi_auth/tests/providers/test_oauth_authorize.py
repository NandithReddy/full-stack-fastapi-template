import pytest
from duck import AsyncHTTPRequest
from duck.request import TestingRequestAdapter
from fastapi_auth._context import Context
from fastapi_auth._storage import SecondaryStorage
from fastapi_auth.social_providers.oauth import (
    OAuth2AuthorizationRequestData,
    OAuth2Provider,
)

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "query_params",
    [
        {},
        {"response_type": "invalid"},
    ],
)
async def test_invalid_request_when_response_type_is_missing_or_invalid(
    oauth_provider: OAuth2Provider, context: Context, query_params: dict
):
    request = AsyncHTTPRequest(
        TestingRequestAdapter(
            method="GET",
            url="http://localhost:8000/test/authorize",
            query_params={
                "client_id": "test_client_id",
                "redirect_uri": "http://valid-auth-server.com/callback",
                **query_params,
            },
        )
    )

    response = await oauth_provider.authorize(request, context)

    assert response.status_code == 302
    assert response.headers is not None
    assert "Location" in response.headers
    assert "error=invalid_request" in response.headers["Location"]


async def test_authorize_redirects_to_provider(
    oauth_provider: OAuth2Provider,
    context: Context,
    secondary_storage: SecondaryStorage,
):
    request = AsyncHTTPRequest(
        TestingRequestAdapter(
            method="GET",
            url="http://localhost:8000/test/authorize",
            query_params={
                "redirect_uri": "http://valid-auth-server.com/callback",
                "state": "test_state",
                "response_type": "code",
                "code_challenge": "test",
                "code_challenge_method": "S256",
            },
        )
    )

    response = await oauth_provider.authorize(request, context)

    assert response.status_code == 302
    assert response.headers is not None
    assert "Location" in response.headers

    location = response.headers["Location"]
    assert location.startswith(oauth_provider.authorization_endpoint)
    assert "client_id=test_client_id" in location
    assert "scope=openid+email+profile" in location
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Ftest%2Fcallback" in location

    state = location.split("state=")[1].split("&")[0]

    raw_authorization_request_data = secondary_storage.get(
        f"oauth:authorization_request:{state}"
    )

    assert raw_authorization_request_data is not None

    authorization_request_data = OAuth2AuthorizationRequestData.model_validate_json(
        raw_authorization_request_data
    )

    assert (
        authorization_request_data.redirect_uri
        == "http://valid-auth-server.com/callback"
    )
    assert authorization_request_data.state == state
    assert authorization_request_data.code_challenge == "test"
    assert authorization_request_data.code_challenge_method == "S256"


async def test_authorize_requires_redirect_uri(
    oauth_provider: OAuth2Provider, context: Context
):
    request = AsyncHTTPRequest(
        TestingRequestAdapter(
            method="GET", url="http://localhost:8000/test/authorize", query_params={}
        )
    )

    response = await oauth_provider.authorize(request, context)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


async def test_invalid_redirect_uri_error(
    oauth_provider: OAuth2Provider, context: Context
):
    request = AsyncHTTPRequest(
        TestingRequestAdapter(
            method="GET",
            url="http://localhost:8000/test/authorize",
            query_params={
                "client_id": "test_client_id",
                "redirect_uri": "http://malicious.com/callback",  # Unregistered redirect URI
                "response_type": "code",
            },
        )
    )

    response = await oauth_provider.authorize(request, context)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_redirect_uri"}
