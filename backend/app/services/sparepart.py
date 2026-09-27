"""备件器材业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "sparepart"
REQUIRED_FIELDS = ["备件编号", "备件名称", "适用型号"]
STATUS_ORDER = ["正常可用", "储备不足", "已冻结", "已耗尽"]
ACTION_RULES = {"冻结备件", "解冻备件", "登记耗尽", "登记领用"}
BATCH_ACTIONS = {"冻结备件", "解冻备件"}
QUANTITY_FIELDS = ("结存数量", "库存下限")
TEXT_FIELDS = ("计量单位", "存放库位", "保管人员")
FROZEN = "已冻结"
EXHAUSTED = "已耗尽"


def _parse_quantity(value: Any, field: str) -> tuple[int | None, str | None]:
    """把数量字段解析成非负整数；负数、小数分别拦下并指出差在哪里。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0, None
    if isinstance(value, bool):
        return None, f"{field}应为非负整数（收到布尔值 {value}）"
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not value.is_integer():
            return None, f"{field}不能填小数（收到 {value}），应为非负整数"
        number = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.lstrip("+-").isdigit():
            number = int(text)
        else:
            try:
                float(text)
            except ValueError:
                return None, f"{field}应为非负整数（收到 {text}）"
            return None, f"{field}不能填小数（收到 {text}），应为非负整数"
    else:
        return None, f"{field}应为非负整数（收到 {value}）"
    if number < 0:
        return None, f"{field}不能为负数（收到 {number}）"
    return number, None


def _refresh(entry: dict[str, Any]) -> dict[str, Any]:
    """按结存数量、库存下限与存放库位重算状态、可用量与异常标记，保证列表前后一致。"""
    stock = int(entry.get("结存数量") or 0)
    lower = int(entry.get("库存下限") or 0)
    if entry.get("status") == FROZEN:
        status = FROZEN
    elif stock <= 0:
        status = EXHAUSTED
    elif stock < lower:
        status = "储备不足"
    else:
        status = "正常可用"
    entry["status"] = status
    entry["备件状态"] = status
    reasons: list[str] = []
    if status != EXHAUSTED and stock < lower:
        reasons.append("结存数量低于下限")
    if not str(entry.get("存放库位") or "").strip():
        reasons.append("存放库位为空")
    entry["abnormal"] = bool(reasons)
    entry["异常原因"] = "、".join(reasons)
    # 已冻结与已耗尽的备件不参与可用量统计
    entry["可用数量"] = 0 if status in (FROZEN, EXHAUSTED) else stock
    entry["pending"] = status != EXHAUSTED
    return entry


class SparepartService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        abnormal: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [_refresh(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("备件编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if abnormal:
            rows = [row for row in rows if row.get("abnormal")]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return _refresh(entry) if entry is not None else None

    def stats(self) -> dict[str, int]:
        """可用量统计：已冻结、已耗尽的结存数量不计入可用量。"""
        rows = [_refresh(row) for row in store.rows(MODULE)]
        return {
            "可用量": sum(int(row.get("结存数量") or 0) for row in rows if row.get("status") not in (FROZEN, EXHAUSTED)),
            "正常可用": sum(1 for row in rows if row.get("status") == "正常可用"),
            "储备不足": sum(1 for row in rows if row.get("status") == "储备不足"),
            "已冻结": sum(1 for row in rows if row.get("status") == FROZEN),
            "已耗尽": sum(1 for row in rows if row.get("status") == EXHAUSTED),
            "异常备件": sum(1 for row in rows if row.get("abnormal")),
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        numbers: dict[str, int] = {}
        for field in QUANTITY_FIELDS:
            number, error = _parse_quantity(values.get(field), field)
            if error:
                return None, error
            numbers[field] = int(number or 0)
        code = str(values["备件编号"]).strip()
        rows = store.rows(MODULE)
        existing = next((row for row in rows if str(row.get("备件编号", "")).strip() == code), None)
        if existing is not None:
            # 备件编号重复登记：合并成一条，结存数量累加，其余字段有值才覆盖
            existing["结存数量"] = int(existing.get("结存数量") or 0) + numbers["结存数量"]
            if str(values.get("库存下限") or "").strip() or isinstance(values.get("库存下限"), (int, float)):
                existing["库存下限"] = numbers["库存下限"]
            for field in REQUIRED_FIELDS[1:] + list(TEXT_FIELDS):
                text = str(values.get(field) or "").strip()
                if text:
                    existing[field] = text
            _refresh(existing)
            return existing, f"备件编号 {code} 已登记过，已合并到原有记录（结存数量累加为 {existing['结存数量']}）"
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field)).strip() for field in REQUIRED_FIELDS})
        entry["结存数量"] = numbers["结存数量"]
        entry["库存下限"] = numbers["库存下限"]
        for field in TEXT_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        entry["status"] = STATUS_ORDER[0]
        _refresh(entry)
        rows.append(entry)
        return entry, "备件器材已登记"

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"备件器材 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于备件器材可执行范围"
        _refresh(entry)
        code = entry.get("备件编号", entry_id)
        if action == "冻结备件":
            if entry["status"] == FROZEN:
                return None, f"备件器材 {code} 已处于冻结状态，无需重复冻结"
            if entry["status"] == EXHAUSTED:
                return None, f"备件器材 {code} 已耗尽，无需冻结"
            entry["status"] = FROZEN
            message = f"备件器材 {code} 已冻结，冻结期间不能领用"
        elif action == "解冻备件":
            if entry["status"] != FROZEN:
                return None, f"备件器材 {code} 当前未冻结，无需解冻"
            entry["status"] = STATUS_ORDER[0]  # 交给 _refresh 按结存重新推导
            message = f"备件器材 {code} 已解冻"
        elif action == "登记耗尽":
            if entry["status"] == EXHAUSTED:
                return None, f"备件器材 {code} 已登记为耗尽"
            if entry["status"] == FROZEN:
                return None, f"备件器材 {code} 已冻结，请先解冻再登记耗尽"
            entry["结存数量"] = 0
            entry["status"] = EXHAUSTED
            message = f"备件器材 {code} 已登记耗尽"
        else:  # 登记领用
            if entry["status"] == FROZEN:
                return None, f"备件器材 {code} 已冻结，冻结期间不能领用，请先解冻"
            if entry["status"] == EXHAUSTED:
                return None, f"备件器材 {code} 已耗尽，无库存可领"
            quantity, error = _parse_quantity((values or {}).get("领用数量"), "领用数量")
            if error:
                return None, error
            if not quantity or quantity <= 0:
                return None, "领用数量应为正整数"
            stock = int(entry.get("结存数量") or 0)
            if quantity > stock:
                return None, f"备件器材 {code} 领用数量 {quantity} 超过结存数量 {stock}"
            entry["结存数量"] = stock - quantity
            message = f"备件器材 {code} 已领用 {quantity}，结存 {entry['结存数量']}"
        _refresh(entry)
        return entry, message

    def run_batch_action(
        self,
        action: str,
        ids: list[int],
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """批量冻结/解冻：逐条执行、逐条给出结果，前端把每条结果写回列表。"""
        if action not in BATCH_ACTIONS:
            return None, f"动作「{action}」不支持批量执行，仅支持批量冻结、批量解冻"
        results: list[dict[str, Any]] = []
        for entry_id in ids:
            entry, message = self.run_action(entry_id, action)
            results.append({"id": entry_id, "ok": entry is not None, "message": message, "entry": entry})
        done = sum(1 for item in results if item["ok"])
        return results, f"批量{action}完成：成功 {done} 条，失败 {len(results) - done} 条"
