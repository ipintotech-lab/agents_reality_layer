"""Worker process entrypoint.

Runs the read-after-write verifier loop. In persistence mode it reconstructs pending
actions from the append-only ``action_event`` log, so the worker is safe to restart.
"""

from __future__ import annotations

import logging

from reality_layer.actions.service import ActionService
from reality_layer.config import get_settings
from reality_layer.connectors.clients import ShopifyHttpClient
from reality_layer.connectors.shopify import ShopifyConnector
from reality_layer.worker.verifier import ReadOrder, VerifierWorker
from reality_layer.world_state.service import WorldStateService


def build_worker() -> VerifierWorker:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    shopify_normalizer = ShopifyConnector()
    read_order: ReadOrder
    if settings.shopify_domain and settings.shopify_access_token:
        read_order = ShopifyHttpClient(
            settings.shopify_domain, settings.shopify_access_token
        ).read_order
    else:
        # No credentials configured: fall back to the in-memory test connector so a
        # local rehearsal without Shopify still exercises the loop.
        read_order = shopify_normalizer.read_order

    session_factory = None
    if settings.persistence_enabled:
        from reality_layer.db.session import SessionLocal

        session_factory = SessionLocal

    return VerifierWorker(
        action_service=ActionService(),
        world_state_service=WorldStateService(),
        read_order=read_order,
        normalizer=shopify_normalizer,
        settings=settings,
        session_factory=session_factory,
    )


def main() -> None:  # pragma: no cover - process entrypoint
    build_worker().run_forever()


if __name__ == "__main__":  # pragma: no cover
    main()
