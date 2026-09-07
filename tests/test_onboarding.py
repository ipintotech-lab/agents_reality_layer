from reality_layer.config import Settings
from reality_layer.connectors.onboarding import check_connector, check_connectors


class HealthyShopify:
    def __init__(self, domain: str, token: str) -> None:
        self.domain = domain
        self.token = token

    def health_check(self) -> bool:
        return True


class UnhealthyEasyPost:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def health_check(self) -> bool:
        return False


def test_shopify_check_reports_capabilities_without_credentials() -> None:
    result = check_connector(
        "shopify",
        Settings(shopify_domain="shop.example", shopify_access_token="secret"),
        shopify_factory=HealthyShopify,
    )

    assert result.authenticated
    assert result.read_capability
    assert result.write_capability


def test_easypost_check_reports_failure() -> None:
    result = check_connector(
        "easypost",
        Settings(easypost_api_key="secret"),
        easypost_factory=UnhealthyEasyPost,
    )

    assert not result.authenticated
    assert result.error == "EasyPost health check failed."


def test_missing_credentials_are_actionable_and_secret_free() -> None:
    result = check_connectors(["shopify"], Settings())

    assert result[0]["authenticated"] is False
    assert "credentials" in str(result[0]["error"])
    assert "secret" not in str(result[0])
