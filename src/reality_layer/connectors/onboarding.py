from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import cast

from reality_layer.config import Settings
from reality_layer.connectors.clients import EasyPostHttpClient, ShopifyHttpClient


@dataclass(frozen=True)
class ConnectorCheck:
    connector: str
    authenticated: bool
    read_capability: bool
    write_capability: bool
    error: str | None = None


def check_connector(
    name: str,
    settings: Settings,
    shopify_factory: Callable[[str, str], ShopifyHttpClient] = ShopifyHttpClient,
    easypost_factory: Callable[[str], EasyPostHttpClient] = EasyPostHttpClient,
) -> ConnectorCheck:
    if name == "shopify":
        if not settings.shopify_domain or not settings.shopify_access_token:
            return ConnectorCheck(
                name, False, False, False, "Shopify credentials are not configured."
            )
        try:
            shopify = shopify_factory(settings.shopify_domain, settings.shopify_access_token)
            healthy = shopify.health_check()
        except (RuntimeError, ValueError, OSError) as exc:
            return ConnectorCheck(name, False, False, False, str(exc))
        return ConnectorCheck(
            name,
            healthy,
            healthy,
            healthy,
            None if healthy else "Shopify health check failed.",
        )

    if name == "easypost":
        if not settings.easypost_api_key:
            return ConnectorCheck(name, False, False, False, "EasyPost API key is not configured.")
        try:
            easypost = easypost_factory(settings.easypost_api_key)
            healthy = easypost.health_check()
        except (RuntimeError, ValueError, OSError) as exc:
            return ConnectorCheck(name, False, False, False, str(exc))
        return ConnectorCheck(
            name,
            healthy,
            healthy,
            False,
            None if healthy else "EasyPost health check failed.",
        )

    raise ValueError(f"Unsupported connector: {name}")


def check_connectors(names: list[str], settings: Settings) -> list[dict[str, object]]:
    return [asdict(check_connector(name, settings)) for name in names]


def preflight_connectors(settings: Settings) -> dict[str, object]:
    """Check the connector capabilities required for the live MVP demo."""
    return _preflight_connectors(
        settings,
        shopify_factory=ShopifyHttpClient,
        easypost_factory=EasyPostHttpClient,
    )


def preflight_demo(
    settings: Settings,
    order_id: str | None = None,
    shopify_factory: Callable[[str, str], ShopifyHttpClient] = ShopifyHttpClient,
    easypost_factory: Callable[[str], EasyPostHttpClient] = EasyPostHttpClient,
) -> dict[str, object]:
    """Run connector and optional target-order checks for the live MVP demo."""
    result = _preflight_connectors(
        settings,
        shopify_factory=shopify_factory,
        easypost_factory=easypost_factory,
    )
    if order_id is None:
        return result

    connectors = cast(list[dict[str, object]], result["connectors"])
    shopify_result = next(
        connector for connector in connectors if connector["connector"] == "shopify"
    )
    if shopify_result["authenticated"] and shopify_result["read_capability"]:
        try:
            order = shopify_factory(
                settings.shopify_domain, settings.shopify_access_token
            ).read_order(order_id)
            order_check = validate_demo_order(order, order_id)
        except (RuntimeError, ValueError, OSError) as exc:
            order_check = {
                "eligible": False,
                "order_id": order_id,
                "failures": ["order.read_failed"],
                "error": str(exc),
            }
    else:
        order_check = {
            "eligible": False,
            "order_id": order_id,
            "failures": ["order.connector_unavailable"],
        }
    result["demo_order"] = order_check
    if not bool(order_check["eligible"]):
        result["ready"] = False
        failures = cast(list[str], result["failures"])
        result["failures"] = [
            *failures,
            *cast(list[str], order_check["failures"]),
        ]
    return result


def _preflight_connectors(
    settings: Settings,
    *,
    shopify_factory: Callable[[str, str], ShopifyHttpClient],
    easypost_factory: Callable[[str], EasyPostHttpClient],
) -> dict[str, object]:
    results = [
        asdict(
            check_connector(
                "shopify",
                settings,
                shopify_factory=shopify_factory,
                easypost_factory=easypost_factory,
            )
        ),
        asdict(
            check_connector(
                "easypost",
                settings,
                shopify_factory=shopify_factory,
                easypost_factory=easypost_factory,
            )
        ),
    ]
    by_name = {str(result["connector"]): result for result in results}
    required = {
        "shopify": ("authenticated", "read_capability", "write_capability"),
        "easypost": ("authenticated", "read_capability"),
    }
    failures = [
        f"{connector}.{capability}"
        for connector, capabilities in required.items()
        for capability in capabilities
        if not bool(by_name[connector][capability])
    ]
    return {
        "ready": not failures,
        "required_capabilities": required,
        "failures": failures,
        "connectors": results,
    }


def validate_demo_order(payload: dict[str, object], order_id: str) -> dict[str, object]:
    """Validate that a live Shopify order is safe for the demo cancellation."""
    actual_id = payload.get("id")
    status = payload.get("financial_status") or payload.get("status")
    fulfillment_status = payload.get("fulfillment_status")
    failures: list[str] = []
    if str(actual_id) != order_id:
        failures.append("order.id_mismatch")
    if not isinstance(status, str) or status.lower() in {
        "cancelled",
        "canceled",
        "closed",
        "voided",
    }:
        failures.append("order.not_open")
    if isinstance(fulfillment_status, str) and fulfillment_status.lower() == "fulfilled":
        failures.append("order.fulfilled")
    return {
        "eligible": not failures,
        "order_id": order_id,
        "status": status,
        "fulfillment_status": fulfillment_status,
        "failures": failures,
    }
