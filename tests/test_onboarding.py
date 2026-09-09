from reality_layer.config import Settings
from reality_layer.connectors.onboarding import (
    ConnectorCheck,
    check_connector,
    check_connectors,
    preflight_connectors,
    preflight_demo,
    validate_demo_order,
    validate_demo_shipment,
)


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


def test_preflight_requires_shopify_write_and_easypost_read(monkeypatch) -> None:
    monkeypatch.setattr(
        "reality_layer.connectors.onboarding.check_connector",
        lambda name, settings, **factories: ConnectorCheck(
            name, False, False, False, "unavailable"
        ),
    )

    result = preflight_connectors(Settings())

    assert result["ready"] is False
    assert "shopify.authenticated" in result["failures"]
    assert "easypost.authenticated" in result["failures"]


class ReadyShopify:
    def __init__(self, domain: str, token: str) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def read_order(self, order_id: str) -> dict[str, object]:
        return {"id": order_id, "financial_status": "paid"}


class ReadyEasyPost:
    def __init__(self, api_key: str) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def read_tracker(self, tracker_id: str) -> dict[str, object]:
        return {"id": tracker_id, "tracking_code": "1Z999", "status": "in_transit"}


def test_preflight_demo_checks_the_exact_order() -> None:
    result = preflight_demo(
        Settings(
            shopify_domain="shop.example",
            shopify_access_token="secret",
            easypost_api_key="secret",
        ),
        order_id="order-1",
        shopify_factory=ReadyShopify,
        easypost_factory=ReadyEasyPost,
    )

    assert result["ready"] is True
    assert result["demo_order"]["eligible"] is True


def test_preflight_demo_checks_linked_order_and_shipment() -> None:
    result = preflight_demo(
        Settings(
            shopify_domain="shop.example",
            shopify_access_token="secret",
            easypost_api_key="secret",
        ),
        order_id="order-1",
        shipment_id="shp-1",
        shopify_factory=ReadyShopify,
        easypost_factory=ReadyEasyPost,
    )

    assert result["ready"] is True
    assert result["demo_order"]["order_id"] == "order-1"
    assert result["demo_shipment"]["shipment_id"] == "shp-1"


def test_preflight_demo_reports_unsafe_exact_order() -> None:
    class FulfilledShopify(ReadyShopify):
        def read_order(self, order_id: str) -> dict[str, object]:
            return {
                "id": order_id,
                "financial_status": "paid",
                "fulfillment_status": "fulfilled",
            }

    result = preflight_demo(
        Settings(
            shopify_domain="shop.example",
            shopify_access_token="secret",
            easypost_api_key="secret",
        ),
        order_id="order-1",
        shopify_factory=FulfilledShopify,
        easypost_factory=ReadyEasyPost,
    )

    assert result["ready"] is False
    assert result["demo_order"]["failures"] == ["order.fulfilled"]


def test_demo_order_validation_rejects_fulfilled_order() -> None:
    result = validate_demo_order(
        {"id": "order-1", "financial_status": "paid", "fulfillment_status": "fulfilled"},
        "order-1",
    )

    assert result["eligible"] is False
    assert result["failures"] == ["order.fulfilled"]


def test_demo_order_validation_accepts_open_unfulfilled_order() -> None:
    result = validate_demo_order(
        {"id": "order-1", "financial_status": "paid", "fulfillment_status": None},
        "order-1",
    )

    assert result["eligible"] is True


def test_demo_shipment_validation_requires_identity_tracking_and_status() -> None:
    result = validate_demo_shipment(
        {"id": "shp-1", "tracking_code": "1Z999", "status": "in_transit"},
        "shp-1",
    )

    assert result["eligible"] is True


def test_demo_shipment_validation_rejects_missing_tracking_code() -> None:
    result = validate_demo_shipment(
        {"id": "shp-1", "status": "in_transit"},
        "shp-1",
    )

    assert result["eligible"] is False
    assert result["failures"] == ["shipment.missing_tracking_code"]
