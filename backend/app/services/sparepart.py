"""备件器材业务规则：状态流转、字段校验与筛选口径都收在这里。

结存数量与冻结状态在这里串起来：
- 结存数量只接受非负整数，负数、小数、非数字都会被拦下并说明差在哪里；
- 结存低于储备下限、存放库位为空的记录会被打上标记，可单独筛出来；
- 已冻结、已耗尽的备件不参与可用量统计；
- 备件编号重复登记时合并到原记录，不再新增一条。
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "sparepart"
REQUIRED_FIELDS = ["备件编号", "备件名称", "适用型号"]
STATUS_ORDER = ["正常可用", "储备不足", "已冻结", "已耗尽"]
ACTIONS = ["冻结备件", "解冻备件", "登记耗尽"]
TERMINAL_STATUSES = {"已冻结", "已耗尽"}  # 不参与可用量统计的状态
DEFAULT_STOCK_FLOOR = 5  # 储备下限默认值：登记时没填就按这个口径判断储备不足

_INT_TEXT = re.compile(r"^-?\d+$")
_DECIMAL_TEXT = re.compile(r"^-?(?:\d+\.\d+|\.\d+)$")


def _parse_quantity(value: Any) -> tuple[int | None, str | None]:
    """把结存数量收敛成非负整数；拦下时返回说明差在哪里的信息。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0, None
    if isinstance(value, bool):
        return None, f"结存数量填写有误：「{value}」不是数字，请填非负整数"
    if isinstance(value, int):
        quantity = value
    elif isinstance(value, float):
        if value != int(value):
            return None, f"结存数量不能填小数：当前是「{value}」，备件按整件登记，请改填整数"
        quantity = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if _INT_TEXT.fullmatch(text):
            quantity = int(text)
        elif _DECIMAL_TEXT.fullmatch(text):
            return None, f"结存数量不能填小数：当前是「{text}」，备件按整件登记，请改填整数"
        else:
            return None, f"结存数量填写有误：「{text}」不是数字，请填非负整数"
    else:
        return None, f"结存数量填写有误：「{value}」不是数字，请填非负整数"
    if quantity < 0:
        return None, f"结存数量不能为负数：当前填的是 {quantity}，请改为 0 或正整数"
    return quantity, None


def _as_int(value: Any, default: int = 0) -> int:
    """读取已落库的数字字段；历史数据里混进非数字时按默认值处理。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and _INT_TEXT.fullmatch(value.strip()):
        return int(value.strip())
    return default


def _floor_of(entry: dict[str, Any]) -> int:
    """单条备件的储备下限；没登记或登记成非数字时回落到默认下限。"""
    floor = _as_int(entry.get("储备下限"), default=-1)
    return floor if floor >= 0 else DEFAULT_STOCK_FLOOR


def _quantity_of(entry: dict[str, Any]) -> int:
    return max(_as_int(entry.get("结存数量")), 0)


def _stock_status(entry: dict[str, Any]) -> str:
    """按结存推导在库状态：低于下限就是储备不足。"""
    if _quantity_of(entry) < _floor_of(entry):
        return "储备不足"
    return "正常可用"


def _flags_of(entry: dict[str, Any]) -> list[str]:
    """需要单独标记的两类异常：结存低于下限、存放库位为空。"""
    flags: list[str] = []
    if _quantity_of(entry) < _floor_of(entry):
        flags.append("结存低于下限")
    if not str(entry.get("存放库位") or "").strip():
        flags.append("存放库位为空")
    return flags


class SparepartService:
    def _present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """把派生字段写回记录：备件状态与状态机对齐，可用量与标记随结存联动。"""
        status = str(entry.get("status") or STATUS_ORDER[0])
        entry["status"] = status
        entry["备件状态"] = status
        entry["结存数量"] = _quantity_of(entry)
        entry["储备下限"] = _floor_of(entry)
        entry["可用量"] = 0 if status in TERMINAL_STATUSES else entry["结存数量"]
        entry["标记"] = _flags_of(entry)
        entry["pending"] = status != "已耗尽"
        entry["abnormal"] = bool(entry["标记"])
        return entry

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        flagged: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._present(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("备件编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if flagged:
            rows = [row for row in rows if row.get("标记")]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._present(entry) if entry is not None else None

    def summary(self) -> dict[str, Any]:
        """可用量统计：已冻结、已耗尽的备件不计入可用备件与可用结存总量。"""
        rows = [self._present(row) for row in store.rows(MODULE)]
        available = [row for row in rows if row["status"] not in TERMINAL_STATUSES]
        cards = [
            {"label": "可用备件", "value": len(available)},
            {"label": "可用结存总量", "value": sum(int(row["结存数量"]) for row in available)},
            {"label": "储备不足备件", "value": sum(1 for row in rows if row["status"] == "储备不足")},
            {"label": "已冻结备件", "value": sum(1 for row in rows if row["status"] == "已冻结")},
        ]
        return {"cards": cards}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """登记备件：先校验再落库；备件编号重复时合并到原记录而不是新增。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        quantity, error = _parse_quantity(values.get("结存数量"))
        if error:
            return None, error
        assert quantity is not None
        code = str(values.get("备件编号")).strip()
        existing = next(
            (row for row in store.rows(MODULE) if str(row.get("备件编号", "")).strip() == code),
            None,
        )
        if existing is not None:
            return self._merge_into(existing, values, quantity)
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field)).strip() for field in REQUIRED_FIELDS})
        entry["结存数量"] = quantity
        for field in ["计量单位", "存放库位", "保管人员"]:
            entry[field] = str(values.get(field) or "").strip()
        floor = _as_int(values.get("储备下限"), default=-1)
        entry["储备下限"] = floor if floor >= 0 else DEFAULT_STOCK_FLOOR
        entry["status"] = _stock_status(entry)
        rows.append(entry)
        return self._present(entry), "备件器材已登记"

    def _merge_into(
        self,
        existing: dict[str, Any],
        values: dict[str, Any],
        quantity: int,
    ) -> tuple[dict[str, Any], str]:
        """重复编号合并：结存累加、资料补齐；冻结状态不随合并改变。"""
        before = _quantity_of(existing)
        existing["结存数量"] = before + quantity
        for field in ["备件名称", "适用型号", "计量单位", "存放库位", "保管人员"]:
            text = str(values.get(field) or "").strip()
            if text:
                existing[field] = text
        floor = _as_int(values.get("储备下限"), default=-1)
        if floor >= 0:
            existing["储备下限"] = floor
        if existing.get("status") == "已冻结":
            pass  # 已冻结的备件保持冻结，只累加结存
        elif existing["结存数量"] == 0 and existing.get("status") == "已耗尽":
            pass  # 耗尽后没有新入库数量，维持已耗尽
        else:
            existing["status"] = _stock_status(existing)
        after = existing["结存数量"]
        message = (
            f"备件编号 {existing.get('备件编号')} 已登记过，已合并为一条："
            f"结存 {before} + {quantity} = {after}"
        )
        return self._present(existing), message

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, bool, str]:
        """执行单条动作；不允许的流转会被拦下并说明原因。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, False, f"备件器材 {entry_id} 不存在或已归档"
        if action not in ACTIONS:
            return None, False, f"动作「{action}」不属于备件器材可执行范围"
        status = str(entry.get("status") or STATUS_ORDER[0])
        if action == "冻结备件":
            if status == "已冻结":
                return self._present(entry), False, f"备件器材 {entry_id} 已是冻结状态，未重复冻结"
            if status == "已耗尽":
                return self._present(entry), False, f"备件器材 {entry_id} 已耗尽，没有可冻结的库存"
            entry["status"] = "已冻结"
            message = "备件器材已冻结，冻结期间不计入可用量"
        elif action == "解冻备件":
            if status != "已冻结":
                return self._present(entry), False, f"备件器材 {entry_id} 当前未冻结，无需解冻"
            entry["status"] = _stock_status(entry)
            message = f"备件器材已解冻，状态恢复为{entry['status']}"
        else:  # 登记耗尽
            if status == "已耗尽":
                return self._present(entry), False, f"备件器材 {entry_id} 已登记过耗尽"
            entry["status"] = "已耗尽"
            entry["结存数量"] = 0
            message = "备件器材已登记耗尽，结存数量清零"
        return self._present(entry), True, message

    def run_batch_action(
        self,
        action: str,
        entry_ids: list[int],
    ) -> tuple[list[dict[str, Any]], str]:
        """批量冻结/解冻：逐条执行、逐条给出结果，单条失败不影响其他记录。"""
        if action not in ACTIONS:
            return [], f"动作「{action}」不属于备件器材可执行范围"
        results: list[dict[str, Any]] = []
        for entry_id in entry_ids:
            entry, ok, message = self.run_action(entry_id, action)
            results.append({"id": entry_id, "ok": ok, "message": message, "entry": entry})
        done = sum(1 for item in results if item["ok"])
        return results, f"共提交 {len(results)} 条，成功 {done} 条，失败 {len(results) - done} 条"
