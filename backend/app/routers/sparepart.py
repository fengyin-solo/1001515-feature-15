"""备件器材接口：维护备件器材，覆盖冻结备件、解冻备件、登记耗尽等动作。

结存与冻结在这里串起来：列表带回可用量与异常标记，批量冻结/解冻逐条给出结果，
统计口径里已冻结、已耗尽的备件不参与可用量。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchActionPayload, BatchActionResult, EntryPayload, PageResult
from app.services.sparepart import SparepartService

router = APIRouter(prefix="/api/sparepart", tags=["备件器材"])

service = SparepartService()

LIST_FIELDS = ["备件编号", "备件名称", "适用型号", "结存数量", "储备下限", "计量单位", "存放库位", "可用量", "保管人员", "备件状态", "标记"]
STATUSES = ["正常可用", "储备不足", "已冻结", "已耗尽"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按备件编号检索"),
    status: str | None = Query(default=None, description="正常可用、储备不足、已冻结、已耗尽"),
    flagged: bool = Query(default=False, description="只看结存低于下限或存放库位为空的备件"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按备件编号、状态与异常标记过滤备件器材列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, flagged=flagged, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary() -> dict[str, Any]:
    """可用量统计：已冻结、已耗尽的备件不参与可用备件与可用结存总量。"""
    return service.summary()


@router.post("/batch-actions", response_model=BatchActionResult)
def run_batch_action(payload: BatchActionPayload) -> BatchActionResult:
    """对勾选的多条备件一次提交冻结或解冻，逐条给出结果并写回列表。"""
    if not payload.ids:
        return BatchActionResult(ok=False, message="请先勾选要处理的备件器材")
    results, message = service.run_batch_action(payload.action, payload.ids)
    if not results:
        return BatchActionResult(ok=False, message=message)
    ok = all(item["ok"] for item in results)
    return BatchActionResult(ok=ok, message=message, results=results)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出备件器材清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "sparepart", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条备件器材明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"备件器材 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条备件器材：结存数量填成负数或小数会被拦下并说明原因；备件编号重复时合并成一条。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条备件器材执行冻结备件、解冻备件、登记耗尽；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, ok, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=ok, message=message, entry=entry)
