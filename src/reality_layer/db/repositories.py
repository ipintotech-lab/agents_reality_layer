from typing import Any

from sqlalchemy import Select, select


def tenant_select(model: Any, tenant_id: str) -> Select[Any]:
    return select(model).where(model.tenant_id == tenant_id)


def tenant_get_by_id(model: Any, tenant_id: str, id_column: str, id_value: Any) -> Select[Any]:
    return tenant_select(model, tenant_id).where(getattr(model, id_column) == id_value)
