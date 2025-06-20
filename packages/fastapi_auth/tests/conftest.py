import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from duck.request import AsyncHTTPRequest
from fastapi_auth._context import Context
from fastapi_auth._issuer import AuthorizationCodeGrantData, Issuer
from fastapi_auth._storage import AccountsStorage, SecondaryStorage
from fastapi_auth.exceptions import FastAPIAuthException
from fastapi_auth.social_providers.oauth import OAuth2LinkCodeData
from passlib.context import CryptContext

pytestmark = pytest.mark.asyncio

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass
class SocialAccount:
    id: str
    user_id: str
    provider_user_id: str
    provider: str
    access_token: str | None = None
    refresh_token: str | None = None
    access_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    scope: str | None = None


@dataclass
class User:
    id: str
    email: str
    hashed_password: str
    social_accounts: list[SocialAccount]


class MemoryStorage(SecondaryStorage):
    def __init__(self):
        self.data = {}

    def set(self, key: str, value: str):
        self.data[key] = value

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def delete(self, key: str):
        del self.data[key]


class MemoryAccountsStorage:
    def __init__(self):
        self.data = {
            "test": User(
                id="test",
                email="test@example.com",
                hashed_password=pwd_context.hash("password123"),
                social_accounts=[],
            )
        }

    def find_user_by_email(self, email: str) -> User | None:
        return next((user for user in self.data.values() if user.email == email), None)

    def find_user_by_id(self, id: Any) -> User | None:
        return self.data.get(id)

    def create_user(self, *, user_info: dict[str, Any]) -> User:
        if self.find_user_by_email(user_info["email"]) is not None:
            raise ValueError("User already exists")

        if user_info["email"] == "not-allowed@example.com":
            raise FastAPIAuthException(
                "email_not_invited",
                "This email has not yet been invited to join FastAPI Cloud",
            )

        user = User(
            id=user_info["id"],
            email=user_info["email"],
            hashed_password=pwd_context.hash(user_info.get("password", "")),
            social_accounts=[],
        )

        self.data[user_info["id"]] = user

        return user

    def find_social_account(
        self,
        provider: str,
        provider_user_id: str,
    ) -> SocialAccount | None:
        for user in self.data.values():
            for social_account in user.social_accounts:
                if (
                    social_account.provider == provider
                    and social_account.provider_user_id == provider_user_id
                ):
                    return social_account
        return None

    def create_social_account(
        self,
        *,
        user_id: str,
        provider: str,
        provider_user_id: str,
        access_token: str | None,
        refresh_token: str | None,
        access_token_expires_at: datetime | None,
        refresh_token_expires_at: datetime | None,
        scope: str | None,
        user_info: dict[str, Any],
    ) -> SocialAccount:
        if user_id not in self.data:
            raise ValueError("User does not exist")

        user = self.data[user_id]

        social_account = SocialAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=access_token_expires_at,
            refresh_token_expires_at=refresh_token_expires_at,
            scope=scope,
        )

        user.social_accounts.append(social_account)

        self.data[user_id] = user

        return social_account

    def update_social_account(
        self,
        social_account_id: str,
        *,
        access_token: str | None,
        refresh_token: str | None,
        access_token_expires_at: datetime | None,
        refresh_token_expires_at: datetime | None,
        scope: str | None,
        user_info: dict[str, Any],
    ) -> SocialAccount:
        social_account = next(
            (
                social_account
                for user in self.data.values()
                for social_account in user.social_accounts
                if social_account.id == social_account_id
            ),
            None,
        )

        if social_account is None:
            raise ValueError("Social account does not exist")

        social_account.access_token = access_token
        social_account.refresh_token = refresh_token
        social_account.access_token_expires_at = access_token_expires_at
        social_account.refresh_token_expires_at = refresh_token_expires_at
        social_account.scope = scope

        return social_account


@pytest.fixture
def secondary_storage() -> SecondaryStorage:
    return MemoryStorage()


@pytest.fixture
def accounts_storage() -> AccountsStorage:
    return MemoryAccountsStorage()


@pytest.fixture
def logged_in_user(accounts_storage: MemoryAccountsStorage) -> User:
    return accounts_storage.find_user_by_email("test@example.com")


@pytest.fixture
def context(
    secondary_storage: SecondaryStorage,
    accounts_storage: AccountsStorage,
    logged_in_user: User,
) -> Context:
    def _get_user_from_request(request: AsyncHTTPRequest) -> User | None:
        if request.headers.get("Authorization") == "Bearer test":
            return logged_in_user

        return None

    return Context(
        secondary_storage=secondary_storage,
        accounts_storage=accounts_storage,
        create_token=lambda id: (f"token-{id}", 0),
        get_user_from_request=_get_user_from_request,
        trusted_origins=["valid-frontend.com"],
    )


@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


@pytest.fixture
def expired_code(secondary_storage: SecondaryStorage) -> str:
    code = "test"
    secondary_storage.set(
        f"oauth:code:{code}",
        AuthorizationCodeGrantData(
            user_id="test",
            expires_at=datetime.now(tz=timezone.utc) - timedelta(seconds=1),
            client_id="test",
            redirect_uri="test",
            code_challenge="test",
            code_challenge_method="S256",
        ).model_dump_json(),
    )
    return code


@pytest.fixture
def valid_code(secondary_storage: SecondaryStorage) -> str:
    code = "test"
    # For code verifier "test", the S256 code challenge is "n4bQgYhMfWWaL-qgxVrQFaO_TxsrC4Is0V1sFbDwCgg"
    secondary_storage.set(
        f"oauth:code:{code}",
        AuthorizationCodeGrantData(
            user_id="test",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=10),
            client_id="test",
            redirect_uri="test",
            code_challenge="n4bQgYhMfWWaL-qgxVrQFaO_TxsrC4Is0V1sFbDwCgg",
            code_challenge_method="S256",
        ).model_dump_json(),
    )
    return code


@pytest.fixture
def valid_link_code(secondary_storage: SecondaryStorage) -> str:
    code = "test"

    secondary_storage.set(
        f"oauth:link_request:{code}",
        OAuth2LinkCodeData(
            expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=10),
            client_id="test",
            redirect_uri="test",
            code_challenge="n4bQgYhMfWWaL-qgxVrQFaO_TxsrC4Is0V1sFbDwCgg",
            code_challenge_method="S256",
            provider_code="1234567890",
        ).model_dump_json(),
    )

    return code
