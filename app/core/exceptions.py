"""Custom exception types for normalized Shopify error handling."""


class ShopifyAPIError(Exception):
    """Non-retryable Shopify API error (GraphQL errors, invalid query, 4xx)."""

    def __init__(self, message: str, shop_domain: str = "", status_code: int = 0):
        self.shop_domain = shop_domain
        self.status_code = status_code
        super().__init__(message)


class ShopifyRateLimitError(Exception):
    """HTTP 429 from Shopify — triggers retry with exponential backoff."""

    def __init__(self, shop_domain: str = "", retry_after: float = 2.0):
        self.shop_domain = shop_domain
        self.retry_after = retry_after
        super().__init__(f"Rate limited by Shopify for {shop_domain}")


class ShopifyConnectionInactiveError(Exception):
    """Store is uninstalled or disabled, blocking all API requests."""

    def __init__(self, shop_domain: str = ""):
        self.shop_domain = shop_domain
        super().__init__(f"Store {shop_domain} is uninstalled or disabled.")
