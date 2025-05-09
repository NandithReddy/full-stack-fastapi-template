from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from .oauth import OAuth2Provider


class DiscordUser(BaseModel):
    id: str = Field(examples=["123456789012345678"])
    username: str = Field(examples=["username"])
    discriminator: str | None = Field(default=None, examples=["0000"])
    avatar: str | None = Field(default=None, examples=["a_1234567890abcdef"])
    avatar_decoration: str | None = None
    email: EmailStr = Field(examples=["user@example.com"])
    verified: bool = Field(examples=[True])
    locale: str | None = Field(default=None, examples=["en-US"])
    mfa_enabled: bool | None = Field(default=None, examples=[False])
    premium_type: int | None = Field(default=None, examples=[0])
    public_flags: int | None = Field(default=None, examples=[0])
    flags: int | None = Field(default=None, examples=[0])
    banner: str | None = Field(default=None, examples=["a_1234567890abcdef"])
    accent_color: int | None = Field(default=None, examples=[16711680])
    global_name: str | None = Field(default=None, examples=["Global Username"])
    avatar_url: str | None = None
    banner_url: str | None = None


class DiscordProvider(OAuth2Provider):
    id = "discord"
    authorization_endpoint = "https://discord.com/oauth2/authorize"
    token_endpoint = "https://discord.com/api/oauth2/token"
    user_info_endpoint = "https://discord.com/api/users/@me"
