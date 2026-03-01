"""
Shopify GraphQL Client — central async executor for Admin + Storefront APIs.

Features:
- Automatic retry with exponential backoff on 429 rate limits
- Structured logging (request_id, shop, operation, duration_ms, status)
- Token masking in all logs
- Normalized error handling (GraphQL errors -> ShopifyAPIError)
"""
import time
import uuid
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import settings
from app.core.exceptions import ShopifyAPIError, ShopifyRateLimitError

logger = logging.getLogger("shopify.client")

_TIMEOUT = 15.0  # seconds
_MAX_RETRIES = 5


class ShopifyGraphQLClient:
    """
    Async Shopify GraphQL client supporting both Admin and Storefront APIs.

    Usage:
        client = ShopifyGraphQLClient(
            shop_domain="mystore.myshopify.com",
            storefront_token="sf_token",
            admin_token="admin_token",
        )
        products = await client.execute_storefront(query, variables)
        orders = await client.execute_admin(query, variables)
    """

    def __init__(
        self,
        shop_domain: str,
        store_id: str | None = None,
        storefront_token: str = "",
        admin_token: str = "",
        api_version: str | None = None,
    ):
        from app.core.crypto import decrypt_token
        
        self.shop_domain = shop_domain
        self.store_id = store_id
        
        # 1) Decrypt tokens ONCE during initialization
        self.storefront_token = decrypt_token(storefront_token)
        self.admin_token = decrypt_token(admin_token)
        
        # Validate and Log for requested debugging step
        if self.admin_token:
            logger.info("Admin token decrypted successfully (len=%d)", len(self.admin_token))
            
        self.api_version = api_version or settings.SHOPIFY_API_VERSION

    # ── Public methods ────────────────────────────────────────────────────

    async def execute_storefront(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a query against the Shopify Storefront API."""
        base_domain = self.shop_domain if self.shop_domain.endswith(".myshopify.com") else f"{self.shop_domain}.myshopify.com"
        url = f"https://{base_domain}/api/{self.api_version}/graphql.json"
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": self.storefront_token,
        }
        return await self._execute(url, headers, query, variables, api_type="storefront")

    async def execute_admin(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a query against the Shopify Admin API."""
        base_domain = self.shop_domain if self.shop_domain.endswith(".myshopify.com") else f"{self.shop_domain}.myshopify.com"
        url = f"https://{base_domain}/admin/api/{self.api_version}/graphql.json"
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.admin_token,
        }
        return await self._execute(url, headers, query, variables, api_type="admin")

    # ── Internal executor with retry ──────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(ShopifyRateLimitError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(_MAX_RETRIES),
        reraise=True,
    )
    async def _execute(
        self,
        url: str,
        headers: dict[str, str],
        query: str,
        variables: dict[str, Any] | None,
        api_type: str,
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.post(
                    url,
                    json={"query": query, "variables": variables or {}},
                    headers=headers,
                )

            duration_ms = int((time.monotonic() - start) * 1000)

            # Structured log — NEVER log tokens
            logger.info(
                "shopify_graphql",
                extra={
                    "request_id": request_id,
                    "shop": self.shop_domain,
                    "api": api_type,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

            # Rate limit handling
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "2.0"))
                raise ShopifyRateLimitError(
                    shop_domain=self.shop_domain, retry_after=retry_after
                )

            # Other HTTP errors
            if response.status_code >= 400:
                raise ShopifyAPIError(
                    message=f"HTTP {response.status_code}: {response.text[:200]}",
                    shop_domain=self.shop_domain,
                    status_code=response.status_code,
                )

            data = response.json()

            # GraphQL-level errors
            if "errors" in data and data["errors"]:
                error_messages = "; ".join(
                    e.get("message", str(e)) for e in data["errors"]
                )
                raise ShopifyAPIError(
                    message=f"GraphQL error: {error_messages}",
                    shop_domain=self.shop_domain,
                )

            return data.get("data", {})

        except (ShopifyRateLimitError, ShopifyAPIError):
            raise
        except httpx.TimeoutException:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "shopify_timeout",
                extra={
                    "request_id": request_id,
                    "shop": self.shop_domain,
                    "api": api_type,
                    "duration_ms": duration_ms,
                },
            )
            raise ShopifyAPIError(
                message=f"Request timed out after {_TIMEOUT}s",
                shop_domain=self.shop_domain,
            )
        except Exception as e:
            logger.error(
                "shopify_unexpected_error",
                extra={
                    "request_id": request_id,
                    "shop": self.shop_domain,
                    "error": str(e),
                },
            )
            raise ShopifyAPIError(
                message=f"Unexpected error: {str(e)}",
                shop_domain=self.shop_domain,
            )
