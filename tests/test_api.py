from fastapi.routing import APIRoute

from reality_layer.api.app import create_app


def test_healthz() -> None:
    app = create_app()
    health_route = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/healthz"
    )

    assert health_route.endpoint() == {"status": "ok", "version": "0.1.0"}
