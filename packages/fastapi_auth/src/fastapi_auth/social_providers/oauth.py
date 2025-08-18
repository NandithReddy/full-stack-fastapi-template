import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Literal, TypedDict

import httpx
from lia import AsyncHTTPRequest
from pydantic import BaseModel, HttpUrl, TypeAdapter, ValidationError

from fastapi_auth.exceptions import FastAPIAuthException
from fastapi_auth.utils._pkce import validate_pkce
from fastapi_auth.utils._response import Response

from .._context import Context
from .._issuer import AuthorizationCodeGrantData
from .._route import Route
from ..models.oauth_token_response import (
    OAuth2TokenEndpointResponse,
    TokenErrorResponse,
    TokenResponse,
)

logger = logging.getLogger(__name__)


class UserInfo(TypedDict):
    email: str
    id: str


class OAuth2Exception(Exception):
    def __init__(self, error: str, error_description: str):
        self.error = error
        self.error_description = error_description


class OAuth2AuthorizationRequestData(BaseModel):
    redirect_uri: str
    login_hint: str | None
    client_state: str | None
    state: str
    code_challenge: str
    code_challenge_method: Literal["S256"]
    link: bool = False


class OAuth2LinkCodeData(BaseModel):
    expires_at: datetime
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: Literal["S256"]
    provider_code: str


def relative_url(url: str, path: str) -> str:
    parts = url.split("/")
    parts.pop()
    parts.append(path)
    return "/".join(parts)


class OAuth2Provider:
    id: ClassVar[str]
    authorization_endpoint: ClassVar[str]
    token_endpoint: ClassVar[str]
    user_info_endpoint: ClassVar[str]
    scopes: ClassVar[list[str]]
    supports_pkce: ClassVar[bool]

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def _generate_code(self) -> str:
        return str(uuid.uuid4())

    async def authorize(
        self,
        request: AsyncHTTPRequest,
        context: Context,
    ) -> Response:
        """
        Redirect to the provider's authorization page.

        This endpoint works similar to a proxy, we store the actual redirect uri
        in a cookie and then use that to redirect the user back to the client
        once the authorization is complete on the Identity Provider's site.
        """

        redirect_uri = request.query_params.get("redirect_uri")

        if not redirect_uri:
            logger.error("No redirect URI provided")
            return Response.error("invalid_request")

        try:
            redirect_uri = str(TypeAdapter(HttpUrl).validate_python(redirect_uri))
        except ValidationError:
            logger.error("Invalid redirect URI")

            return Response.error("invalid_redirect_uri")

        # TODO: this is where we'll validate the redirect URI against the client
        # when we implement clients :)

        if not context.is_valid_redirect_uri(redirect_uri):
            logger.error("Invalid redirect URI")

            return Response.error("invalid_redirect_uri")

        response_type = request.query_params.get("response_type")

        if not response_type:
            logger.error("No response type provided")

            return Response.error_redirect(
                redirect_uri,
                error="invalid_request",
                error_description="No response type provided",
            )

        if response_type not in ["code", "link_code"]:
            logger.error("Unsupported response type")

            return Response.error_redirect(
                redirect_uri,
                error="invalid_request",
                error_description="Unsupported response type",
            )

        code_challenge = request.query_params.get("code_challenge")
        code_challenge_method = request.query_params.get("code_challenge_method")

        if not code_challenge:
            logger.error("No code challenge provided")

            return Response.error_redirect(
                redirect_uri,
                error="invalid_request",
                error_description="No code challenge provided",
            )

        if code_challenge_method != "S256":
            logger.error("Unsupported code challenge method")

            return Response.error_redirect(
                redirect_uri,
                error="invalid_request",
                error_description="Unsupported code challenge method",
            )

        login_hint = request.query_params.get("login_hint")
        client_state = request.query_params.get("state")
        state = secrets.token_hex(16)

        data = OAuth2AuthorizationRequestData.model_validate(
            {
                "redirect_uri": redirect_uri,
                "login_hint": login_hint,
                "client_state": client_state,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "link": response_type == "link_code",
            }
        )

        context.secondary_storage.set(
            f"oauth:authorization_request:{state}",
            data.model_dump_json(),
            # TODO: ttl
        )

        proxy_redirect_uri = relative_url(str(request.url), "callback")

        query_params = self.build_authorization_params(
            state=state,
            proxy_redirect_uri=proxy_redirect_uri,
            response_type="code",
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            login_hint=login_hint,
        )

        return Response.redirect(
            self.authorization_endpoint,
            query_params=query_params,
        )

    async def callback(self, request: AsyncHTTPRequest, context: Context) -> Response:
        """
        This callback endpoint is used to exchange the Identity Provider's code
        for a token and then login the user on our side.
        """

        state = request.query_params.get("state")

        if not state:
            logger.error("No state found in request")
            return Response.error(
                "server_error",
                error_description="No state found in request",
            )

        raw_provider_data = context.secondary_storage.get(
            f"oauth:authorization_request:{state}"
        )

        if not raw_provider_data:
            logger.error("No provider data found in secondary storage")

            return Response.error(
                "server_error",
                error_description="Provider data not found",
            )

        try:
            provider_data = OAuth2AuthorizationRequestData.model_validate_json(
                raw_provider_data
            )
        except ValidationError as e:
            logger.error("Invalid provider data", exc_info=e)

            return Response.error(
                "server_error",
                error_description="Invalid provider data",
            )

        code = request.query_params.get("code")

        if not code:
            logger.error("No authorization code received in callback")

            return Response.error_redirect(
                provider_data.redirect_uri,
                error="server_error",
                error_description="No authorization code received in callback",
            )

        if provider_data.link:
            return self._link_flow(request, context, provider_data, code)

        redirect_uri = provider_data.redirect_uri

        try:
            user_info, token_response = self._fetch_user_info(request, code, context)
        except OAuth2Exception as e:
            return Response.error_redirect(
                redirect_uri,
                error=e.error,
                error_description=e.error_description,
            )

        email = user_info["email"]
        provider_user_id = user_info["id"]

        social_account = context.accounts_storage.find_social_account(
            provider=self.id,
            provider_user_id=provider_user_id,
        )

        if social_account:
            context.accounts_storage.update_social_account(
                social_account.id,
                access_token=token_response.access_token,
                refresh_token=token_response.refresh_token,
                access_token_expires_at=token_response.access_token_expires_at,
                refresh_token_expires_at=token_response.refresh_token_expires_at,
                scope=token_response.scope,
                user_info=user_info,
            )

            user = context.accounts_storage.find_user_by_id(social_account.user_id)
        else:
            user = context.accounts_storage.find_user_by_email(email)

            if user:
                return Response.error_redirect(
                    redirect_uri,
                    error="account_exists",
                    error_description="An account with this email already exists.",
                )

            try:
                user = context.accounts_storage.create_user(user_info=user_info)
            except FastAPIAuthException as e:
                return Response.error_redirect(
                    redirect_uri,
                    error=e.error,
                    error_description=e.error_description,
                )

            context.accounts_storage.create_social_account(
                user_id=user.id,
                provider=self.id,
                provider_user_id=provider_user_id,
                access_token=token_response.access_token,
                refresh_token=token_response.refresh_token,
                access_token_expires_at=token_response.access_token_expires_at,
                refresh_token_expires_at=token_response.refresh_token_expires_at,
                scope=token_response.scope,
                user_info=user_info,
            )

        code = self._generate_code()

        data = AuthorizationCodeGrantData(
            user_id=str(user.id),
            expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=10),
            client_id=self.client_id,
            redirect_uri=redirect_uri,
            code_challenge=provider_data.code_challenge,
            code_challenge_method=provider_data.code_challenge_method,
        )

        context.secondary_storage.set(
            f"oauth:code:{code}",
            data.model_dump_json(),
        )

        return Response.redirect(
            redirect_uri,
            query_params={"code": code},
        )

    def _link_flow(
        self,
        request: AsyncHTTPRequest,
        context: Context,
        provider_data: OAuth2AuthorizationRequestData,
        provider_code: str,
    ) -> Response:
        data = OAuth2LinkCodeData(
            expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=10),
            client_id=self.client_id,
            redirect_uri=provider_data.redirect_uri,
            code_challenge=provider_data.code_challenge,
            code_challenge_method=provider_data.code_challenge_method,
            provider_code=provider_code,
        )

        code = self._generate_code()

        context.secondary_storage.set(
            f"oauth:link_request:{code}",
            data.model_dump_json(),
        )

        return Response.redirect(
            provider_data.redirect_uri,
            query_params={"link_code": code},
        )

    def build_authorization_params(
        self,
        state: str,
        proxy_redirect_uri: str,
        response_type: str,
        code_challenge: str,
        code_challenge_method: str,
        login_hint: str | None,
    ) -> dict:
        """Build authorization request parameters.

        Override this method to customize authorization parameters.
        For example, to force a specific response_type or add extra params.
        """
        params = {
            "client_id": self.client_id,
            "scope": " ".join(self.scopes),
            "redirect_uri": proxy_redirect_uri,
            "state": state,
            "response_type": response_type,
        }

        # Add PKCE parameters if provider supports them
        if self.supports_pkce:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = code_challenge_method

        # Add login_hint if provided
        if login_hint:
            params["login_hint"] = login_hint

        return params

    def get_code_verifier(
        self, request: AsyncHTTPRequest | None, context: Context | None
    ) -> str | None:
        """Get code_verifier for PKCE flow.

        Override this method to provide code_verifier for token exchange.
        """
        return None

    def build_token_exchange_params(
        self, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict:
        """Build token exchange request parameters.

        Override this method to customize token exchange parameters.
        """
        params = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        if code_verifier:
            params["code_verifier"] = code_verifier

        return params

    def send_token_request(self, data: dict[str, Any]) -> httpx.Response:
        """Send token exchange request.

        Override this method to customize how the request is sent
        """
        return httpx.post(
            self.token_endpoint,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
        )

    def parse_token_response(
        self, response: httpx.Response
    ) -> OAuth2TokenEndpointResponse | None:
        """Parse token exchange response.

        Override this method to handle different response formats
        (e.g., JSON instead of query string).
        """
        try:
            return OAuth2TokenEndpointResponse.model_validate_json(response.text)
        except ValidationError as e:
            logger.error(f"Failed to parse token response: {str(e)}")
            return None

    def _exchange_code(
        self,
        code: str,
        redirect_uri: str,
        request: AsyncHTTPRequest | None = None,
        context: Context | None = None,
    ) -> OAuth2TokenEndpointResponse | None:
        try:
            # Get code_verifier if needed
            code_verifier = self.get_code_verifier(request, context)

            # Build request parameters
            params = self.build_token_exchange_params(code, redirect_uri, code_verifier)

            # Send the request
            response = self.send_token_request(params)
            response.raise_for_status()

            # Parse the response
            return self.parse_token_response(response)

        except httpx.HTTPStatusError as e:
            logger.warning(
                f"HTTP error during token exchange: {e.response.status_code} - {e.response.text}"
            )
            return None
        except (httpx.RequestError, ValidationError) as e:
            logger.error(f"Failed to exchange code for token: {str(e)}")
            return None

    def _fetch_user_info(
        self, request: AsyncHTTPRequest, code: str, context: Context | None = None
    ) -> tuple[UserInfo, TokenResponse]:
        proxy_redirect_uri = relative_url(str(request.url), "callback")

        token_response = self._exchange_code(code, proxy_redirect_uri, request, context)

        if token_response is None or token_response.is_error():
            if token_response:
                assert isinstance(token_response.root, TokenErrorResponse)

                logger.error(f"Token exchange failed: {token_response.root.error}")

            raise OAuth2Exception(
                error="server_error",
                error_description="Token exchange failed",
            )

        assert isinstance(token_response.root, TokenResponse)

        try:
            user_info = self.fetch_user_info(token_response.root.access_token)
        except Exception as e:
            logger.error(f"Failed to fetch user info: {str(e)}")
            raise OAuth2Exception(
                error="server_error",
                error_description="Failed to fetch user info",
            )

        email = user_info.get("email")

        if not email:
            logger.error("No email found in user info")

            raise OAuth2Exception(
                error="server_error",
                error_description="No email found in user info",
            )

        provider_user_id = user_info.get("id")

        if not provider_user_id:
            logger.error("No provider user ID found in user info")

            raise OAuth2Exception(
                error="server_error",
                error_description="No provider user ID found in user info",
            )

        return (
            user_info,  # type: ignore
            token_response.root,
        )

    def fetch_user_info(self, token: str) -> dict:
        response = httpx.get(
            self.user_info_endpoint,
            headers={"Authorization": f"Bearer {token}"},
        )
        return response.json()

    async def finalize_link(
        self, request: AsyncHTTPRequest, context: Context
    ) -> Response:
        user = context.get_user_from_request(request)

        if not user:
            return Response.error(
                "unauthorized",
                error_description="Not logged in",
                status_code=401,
            )

        request_data = json.loads(await request.get_body())
        code = request_data.get("link_code")

        if not code:
            logger.error("No link code found in request")

            return Response.error(
                "server_error",
                error_description="No link code found in request",
            )

        data = context.secondary_storage.get(f"oauth:link_request:{code}")

        if not data:
            logger.error("No link data found in secondary storage")

            return Response.error(
                "server_error",
                error_description="No link data found in secondary storage",
            )

        try:
            link_data = OAuth2LinkCodeData.model_validate_json(data)
        except ValidationError as e:
            logger.error("Invalid link data", exc_info=e)

            return Response.error(
                "server_error",
                error_description="Invalid link data",
            )

        if link_data.expires_at < datetime.now(tz=timezone.utc):
            logger.error("Link code has expired")

            return Response.error(
                "server_error",
                error_description="Link code has expired",
            )

        if link_data.code_challenge_method != "S256":
            return Response.error(
                "server_error",
                error_description="Unsupported code challenge method",
            )

        code_verifier = request_data.get("code_verifier")

        if not code_verifier:
            return Response.error(
                "server_error",
                error_description="No code_verifier provided",
            )

        if not validate_pkce(
            link_data.code_challenge,
            link_data.code_challenge_method,
            code_verifier,
        ):
            return Response.error(
                "server_error",
                error_description="Invalid code challenge",
            )

        try:
            user_info, token_response = self._fetch_user_info(
                request, link_data.provider_code, context
            )
        except OAuth2Exception as e:
            return Response.error(
                e.error,
                error_description=e.error_description,
            )

        social_account = context.accounts_storage.find_social_account(
            provider=self.id,
            provider_user_id=user_info["id"],
        )

        if social_account:
            if social_account.user_id != user.id:
                return Response.error(
                    "server_error",
                    error_description="Social account already exists",
                )

            context.accounts_storage.update_social_account(
                social_account.id,
                access_token=token_response.access_token,
                refresh_token=token_response.refresh_token,
                access_token_expires_at=token_response.access_token_expires_at,
                refresh_token_expires_at=token_response.refresh_token_expires_at,
                scope=token_response.scope,
                user_info=user_info,
            )
        else:
            context.accounts_storage.create_social_account(
                user_id=user.id,
                provider=self.id,
                provider_user_id=user_info["id"],
                access_token=token_response.access_token,
                refresh_token=token_response.refresh_token,
                access_token_expires_at=token_response.access_token_expires_at,
                refresh_token_expires_at=token_response.refresh_token_expires_at,
                scope=token_response.scope,
                user_info=user_info,
            )

        return Response(status_code=200, body='{"message": "Link finalized"}')

    @property
    def routes(self) -> list[Route]:
        # TODO: add support for response models (for OpenAPI)
        return [
            Route(
                path=f"/{self.id}/authorize",
                methods=["GET"],
                function=self.authorize,
                operation_id=f"{self.id}_authorize",
            ),
            Route(
                path=f"/{self.id}/callback",
                methods=["GET"],
                function=self.callback,
                operation_id=f"{self.id}_callback",
            ),
            Route(
                path=f"/{self.id}/finalize-link",
                methods=["POST"],
                function=self.finalize_link,
                operation_id=f"{self.id}_finalize_link",
            ),
        ]
