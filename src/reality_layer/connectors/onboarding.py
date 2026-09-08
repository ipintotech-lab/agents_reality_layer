from collections.abc import Callable
from dataclasses import asdict, dataclass

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
    results = check_connectors(["shopify", "easypost"], settings)
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
