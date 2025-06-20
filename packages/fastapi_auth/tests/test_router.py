from fastapi import FastAPI
from fastapi_auth._context import AccountsStorage, SecondaryStorage
from fastapi_auth.router import AuthRouter
from inline_snapshot import snapshot


def test_router(
    secondary_storage: SecondaryStorage,
    accounts_storage: AccountsStorage,
):
    router = AuthRouter(
        providers=[],
        secondary_storage=secondary_storage,
        accounts_storage=accounts_storage,
        get_user_from_request=lambda _: None,
        create_token=lambda _: ("", 0),
        trusted_origins=[],
    )

    app = FastAPI()

    app.include_router(router)

    assert app.openapi() == snapshot(
        {
            "openapi": "3.1.0",
            "info": {"title": "FastAPI", "version": "0.1.0"},
            "paths": {
                "/token": {
                    "post": {
                        "summary": "OAuth 2.0 token endpoint",
                        "operationId": "token",
                        "requestBody": {
                            "content": {
                                "application/x-www-form-urlencoded": {
                                    "schema": {
                                        "$ref": "#/components/schemas/Body_token"
                                    }
                                }
                            },
                            "required": True,
                        },
                        "responses": {
                            "200": {
                                "description": "Successful token response",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/TokenResponse"
                                        }
                                    }
                                },
                            },
                            "400": {
                                "description": "Bad request - invalid parameters or grant",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/TokenErrorResponse"
                                        }
                                    }
                                },
                            },
                            "422": {
                                "description": "Validation Error",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "$ref": "#/components/schemas/HTTPValidationError"
                                        }
                                    }
                                },
                            },
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "AuthorizationCodeGrantRequest": {
                        "properties": {
                            "grant_type": {
                                "type": "string",
                                "const": "authorization_code",
                                "title": "Grant Type",
                                "description": "The OAuth 2.0 grant type",
                            },
                            "client_id": {
                                "type": "string",
                                "title": "Client Id",
                                "description": "The client identifier",
                            },
                            "client_secret": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "title": "Client Secret",
                                "description": "The client secret (for confidential clients)",
                            },
                            "code": {
                                "type": "string",
                                "title": "Code",
                                "description": "The authorization code received from the authorization server",
                            },
                            "redirect_uri": {
                                "type": "string",
                                "title": "Redirect Uri",
                                "description": "The redirect URI used in the authorization request",
                            },
                            "code_verifier": {
                                "type": "string",
                                "title": "Code Verifier",
                                "description": "The PKCE code verifier",
                            },
                            "scope": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "title": "Scope",
                                "description": "Space-delimited list of scopes",
                            },
                        },
                        "type": "object",
                        "required": [
                            "grant_type",
                            "client_id",
                            "code",
                            "redirect_uri",
                            "code_verifier",
                        ],
                        "title": "AuthorizationCodeGrantRequest",
                    },
                    "Body_token": {
                        "properties": {
                            "request": {
                                "oneOf": [
                                    {
                                        "$ref": "#/components/schemas/AuthorizationCodeGrantRequest"
                                    },
                                    {
                                        "$ref": "#/components/schemas/PasswordGrantRequest"
                                    },
                                ],
                                "title": "Request",
                                "discriminator": {
                                    "propertyName": "grant_type",
                                    "mapping": {
                                        "authorization_code": "#/components/schemas/AuthorizationCodeGrantRequest",
                                        "password": "#/components/schemas/PasswordGrantRequest",
                                    },
                                },
                            }
                        },
                        "type": "object",
                        "required": ["request"],
                        "title": "Body_token",
                    },
                    "HTTPValidationError": {
                        "properties": {
                            "detail": {
                                "items": {
                                    "$ref": "#/components/schemas/ValidationError"
                                },
                                "type": "array",
                                "title": "Detail",
                            }
                        },
                        "type": "object",
                        "title": "HTTPValidationError",
                    },
                    "PasswordGrantRequest": {
                        "properties": {
                            "grant_type": {
                                "type": "string",
                                "const": "password",
                                "title": "Grant Type",
                                "description": "The OAuth 2.0 grant type",
                            },
                            "client_id": {
                                "type": "string",
                                "title": "Client Id",
                                "description": "The client identifier",
                            },
                            "client_secret": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "title": "Client Secret",
                                "description": "The client secret (for confidential clients)",
                            },
                            "username": {
                                "type": "string",
                                "title": "Username",
                                "description": "The resource owner username",
                            },
                            "password": {
                                "type": "string",
                                "title": "Password",
                                "description": "The resource owner password",
                            },
                            "scope": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "title": "Scope",
                                "description": "Space-delimited list of scopes",
                            },
                        },
                        "type": "object",
                        "required": ["grant_type", "client_id", "username", "password"],
                        "title": "PasswordGrantRequest",
                    },
                    "TokenErrorResponse": {
                        "properties": {
                            "error": {
                                "type": "string",
                                "enum": [
                                    "invalid_request",
                                    "invalid_client",
                                    "invalid_grant",
                                    "unauthorized_client",
                                    "unsupported_grant_type",
                                    "invalid_scope",
                                ],
                                "title": "Error",
                            },
                            "error_description": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "title": "Error Description",
                            },
                            "error_uri": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "title": "Error Uri",
                            },
                        },
                        "type": "object",
                        "required": ["error"],
                        "title": "TokenErrorResponse",
                    },
                    "TokenResponse": {
                        "properties": {
                            "token_type": {
                                "type": "string",
                                "title": "Token Type",
                                "description": "The type of token, usually 'Bearer'",
                            },
                            "access_token": {
                                "type": "string",
                                "title": "Access Token",
                                "description": "The issued access token",
                            },
                            "expires_in": {
                                "anyOf": [{"type": "integer"}, {"type": "null"}],
                                "title": "Expires In",
                                "description": "Lifetime of the access token in seconds",
                            },
                            "refresh_token": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "title": "Refresh Token",
                                "description": "Token used to obtain new access tokens",
                            },
                            "refresh_token_expires_in": {
                                "anyOf": [{"type": "integer"}, {"type": "null"}],
                                "title": "Refresh Token Expires In",
                                "description": "Lifetime of the refresh token in seconds",
                            },
                            "scope": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "title": "Scope",
                                "description": "Space-delimited list of scopes associated with the access token",
                            },
                        },
                        "type": "object",
                        "required": ["token_type", "access_token"],
                        "title": "TokenResponse",
                    },
                    "ValidationError": {
                        "properties": {
                            "loc": {
                                "items": {
                                    "anyOf": [{"type": "string"}, {"type": "integer"}]
                                },
                                "type": "array",
                                "title": "Location",
                            },
                            "msg": {"type": "string", "title": "Message"},
                            "type": {"type": "string", "title": "Error Type"},
                        },
                        "type": "object",
                        "required": ["loc", "msg", "type"],
                        "title": "ValidationError",
                    },
                }
            },
        }
    )
