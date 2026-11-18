import copy
import hashlib
import math
import struct
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agent import ProposalOperation


class TreeDiffError(ValueError):
    pass


def canonicalize_bot(bot: dict[str, Any]) -> str:
    """Return the canonical semantic representation used for proof and hashing."""
    canonical = copy.deepcopy(bot)
    if not isinstance(canonical, dict):
        raise TreeDiffError("bot must be an object")
    canonical.setdefault("icon", "bot")
    flow = canonical.get("flow")
    if not isinstance(flow, dict) or not isinstance(flow.get("nodes"), list):
        raise TreeDiffError("bot flow must contain a nodes list")
    normalized_nodes = []
    for node in flow["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise TreeDiffError("bot contains an invalid node")
        normalized = copy.deepcopy(node)
        normalized.setdefault("slots", {})
        normalized_nodes.append(normalized)
    flow["nodes"] = sorted(normalized_nodes, key=lambda item: item["id"])
    return _canonical_value(canonical)


def canonical_bot_hash(bot: dict[str, Any]) -> str:
    encoded = canonicalize_bot(bot).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def dump_tree_operations(
    operations: tuple["ProposalOperation", ...] | list["ProposalOperation"],
) -> list[dict[str, Any]]:
    dumped: list[dict[str, Any]] = []
    for operation in operations:
        payload = operation.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        location = payload.get("location")
        if isinstance(location, dict) and "parentId" not in location:
            location["parentId"] = None
        dumped.append(payload)
    return dumped


def derive_tree_operations(
    base: dict[str, Any], result: dict[str, Any]
) -> tuple["ProposalOperation", ...]:
    base_tree = _Tree(base, label="base")
    result_tree = _Tree(result, label="result")
    if not _json_values_equal(
        _immutable_bot_data(base), _immutable_bot_data(result)
    ):
        raise TreeDiffError("result changes bot fields unsupported by public operations")

    draft = copy.deepcopy(base)
    operations: list[ProposalOperation] = []

    metadata: dict[str, Any] = {"op": "setMetadata"}
    for field in ("name", "description"):
        if base.get(field) != result.get(field):
            metadata[field] = copy.deepcopy(result.get(field))
    if len(metadata) > 1:
        operations.append(_operation(metadata))
        draft.update({key: value for key, value in metadata.items() if key != "op"})

    base_ids = set(base_tree.by_id)
    result_ids = set(result_tree.by_id)
    removed_ids = base_ids - result_ids
    remaining_removed = set(removed_ids)
    while remaining_removed:
        current = _Tree(draft, label="draft")
        node_id = next(
            candidate
            for candidate in current.preorder
            if candidate in remaining_removed
            and current.parent[candidate][0] not in remaining_removed
        )
        frontier = _retained_frontier(draft, node_id, result_ids)
        for retained_id in _topological_evacuation_order(frontier, result_tree):
            location = _direct_evacuation_location(
                draft, retained_id, result_tree
            ) or {
                "parentId": None,
                "slot": "root",
                "index": len(draft["flow"]["root"]),
            }
            operations.append(
                _operation(
                    {
                        "op": "moveNode",
                        "nodeId": retained_id,
                        "location": location,
                    }
                )
            )
            _move_node(
                draft,
                retained_id,
                location["parentId"],
                location["slot"],
                location["index"],
            )
        removed_now = _draft_descendants(draft, node_id)
        operations.append(_operation({"op": "removeNode", "nodeId": node_id}))
        _remove_subtree(draft, node_id)
        remaining_removed.difference_update(removed_now)

    common_ids = base_ids & result_ids
    for node_id in result_tree.preorder:
        if node_id not in common_ids:
            continue
        before = base_tree.by_id[node_id]
        after = result_tree.by_id[node_id]
        if before.get("type") == after.get("type"):
            continue
        if set(_slots(before)) != set(_slots(after)):
            raise TreeDiffError(
                f"cannot replace '{node_id}' because it has incompatible slots"
            )
        payload = {
            "op": "replaceNode",
            "nodeId": node_id,
            "actionType": after.get("type"),
            "params": copy.deepcopy(after.get("params")),
        }
        operations.append(_operation(payload))
        draft_node = _nodes_by_id(draft)[node_id]
        draft_node["type"] = payload["actionType"]
        draft_node["params"] = copy.deepcopy(payload["params"])

    for node_id in result_tree.preorder:
        if node_id not in common_ids:
            continue
        before = base_tree.by_id[node_id]
        after = result_tree.by_id[node_id]
        if before.get("type") != after.get("type"):
            continue
        if _json_values_equal(before.get("params"), after.get("params")):
            continue
        payload = {
            "op": "updateNodeParams",
            "nodeId": node_id,
            "params": copy.deepcopy(after.get("params")),
        }
        operations.append(_operation(payload))
        _nodes_by_id(draft)[node_id]["params"] = copy.deepcopy(payload["params"])

    added_ids = result_ids - base_ids
    for node_id in result_tree.preorder:
        if node_id not in added_ids:
            continue
        desired = result_tree.by_id[node_id]
        parent_id, slot, desired_index = result_tree.parent[node_id]
        target = _target(draft, parent_id, slot)
        insertion_index = min(desired_index, len(target))
        payload = {
            "op": "addNode",
            "node": {
                "id": node_id,
                "type": desired.get("type"),
                "params": copy.deepcopy(desired.get("params")),
            },
            "location": {
                "parentId": parent_id,
                "slot": slot,
                "index": insertion_index,
            },
        }
        operations.append(_operation(payload))
        new_node = copy.deepcopy(payload["node"])
        desired_slots = _slots(desired)
        if desired_slots:
            new_node["slots"] = {name: [] for name in desired_slots}
        draft["flow"]["nodes"].append(new_node)
        target.insert(insertion_index, node_id)

    for parent_id, slot, desired_ids in result_tree.containers:
        for index, node_id in enumerate(desired_ids):
            current_parent, current_slot, current_index = _placement(draft, node_id)
            if (current_parent, current_slot, current_index) == (
                parent_id,
                slot,
                index,
            ):
                continue
            payload = {
                "op": "moveNode",
                "nodeId": node_id,
                "location": {
                    "parentId": parent_id,
                    "slot": slot,
                    "index": index,
                },
            }
            operations.append(_operation(payload))
            _move_node(draft, node_id, parent_id, slot, index)

    if len(operations) > 200:
        raise TreeDiffError("derived operation count exceeds the public limit")
    if canonicalize_bot(draft) != canonicalize_bot(result):
        raise TreeDiffError("derived operations do not reproduce the result")
    return tuple(operations)


def _operation(payload: dict[str, Any]) -> "ProposalOperation":
    # Imported lazily because agent owns the public protocol models and imports this module.
    from app.agent import (
        AddNodeOperation,
        MoveNodeOperation,
        RemoveNodeOperation,
        ReplaceNodeOperation,
        SetMetadataOperation,
        UpdateNodeParamsOperation,
    )

    models = {
        "setMetadata": SetMetadataOperation,
        "addNode": AddNodeOperation,
        "removeNode": RemoveNodeOperation,
        "moveNode": MoveNodeOperation,
        "updateNodeParams": UpdateNodeParamsOperation,
        "replaceNode": ReplaceNodeOperation,
    }
    return models[payload["op"]].model_validate(payload)


def _immutable_bot_data(bot: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(bot)
    data.pop("name", None)
    data.pop("description", None)
    data.pop("flow", None)
    data.setdefault("icon", "bot")
    return data


def _canonical_value(value: Any) -> str:
    if value is None:
        return "n;"
    if isinstance(value, bool):
        return "b1;" if value else "b0;"
    if isinstance(value, (int, float)):
        if isinstance(value, int) and abs(value) > 9_007_199_254_740_991:
            raise TreeDiffError("bot contains an unsafe JSON integer")
        number = float(value)
        if not math.isfinite(number):
            raise TreeDiffError("bot contains a non-finite JSON number")
        if number == 0:
            number = 0.0
        return f"d{struct.pack('>d', number).hex()};"
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise TreeDiffError("bot strings must contain only Unicode scalar values")
        return f"s{value.encode('utf-8').hex()};"
    if isinstance(value, list):
        return f"a{len(value)}:" + "".join(_canonical_value(item) for item in value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TreeDiffError("bot contains a non-string object key")
        if any(
            any(0xD800 <= ord(character) <= 0xDFFF for character in key)
            for key in value
        ):
            raise TreeDiffError("bot object keys must contain only Unicode scalar values")
        items = sorted(value.items(), key=lambda item: item[0])
        return f"o{len(items)}:" + "".join(
            _canonical_value(key) + _canonical_value(item) for key, item in items
        )
    raise TreeDiffError("bot contains a non-JSON value")


def _json_values_equal(left: Any, right: Any) -> bool:
    return _canonical_value(left) == _canonical_value(right)


def _slots(node: dict[str, Any]) -> dict[str, list[str]]:
    slots = node.get("slots", {})
    if not isinstance(slots, dict) or any(
        not isinstance(name, str)
        or not isinstance(children, list)
        or not all(isinstance(child, str) for child in children)
        for name, children in slots.items()
    ):
        raise TreeDiffError("node slots are invalid")
    return slots


def _nodes_by_id(bot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in bot["flow"]["nodes"]}


def _target(bot: dict[str, Any], parent_id: str | None, slot: str) -> list[str]:
    if parent_id is None:
        if slot != "root":
            raise TreeDiffError("root placement must use the root slot")
        return bot["flow"]["root"]
    parent = _nodes_by_id(bot).get(parent_id)
    if parent is None or slot not in _slots(parent):
        raise TreeDiffError("operation references an unavailable parent slot")
    return _slots(parent)[slot]


def _placement(bot: dict[str, Any], node_id: str) -> tuple[str | None, str, int]:
    matches: list[tuple[str | None, str, int]] = []
    root = bot["flow"]["root"]
    if node_id in root:
        matches.append((None, "root", root.index(node_id)))
    for parent_id, parent in _nodes_by_id(bot).items():
        for slot, children in _slots(parent).items():
            if node_id in children:
                matches.append((parent_id, slot, children.index(node_id)))
    if len(matches) != 1:
        raise TreeDiffError(f"node '{node_id}' must have exactly one placement")
    return matches[0]


def _move_node(
    bot: dict[str, Any],
    node_id: str,
    parent_id: str | None,
    slot: str,
    index: int,
) -> None:
    current_parent, current_slot, _ = _placement(bot, node_id)
    _target(bot, current_parent, current_slot).remove(node_id)
    target = _target(bot, parent_id, slot)
    if index > len(target):
        raise TreeDiffError("move index is out of range in progressive draft")
    target.insert(index, node_id)


def _draft_descendants(bot: dict[str, Any], node_id: str) -> set[str]:
    by_id = _nodes_by_id(bot)
    found: set[str] = set()
    pending = [node_id]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        for children in _slots(by_id[current]).values():
            pending.extend(children)
    return found


def _retained_frontier(
    bot: dict[str, Any], node_id: str, retained_ids: set[str]
) -> list[str]:
    by_id = _nodes_by_id(bot)
    frontier: list[str] = []

    def visit(current: str) -> None:
        for slot in sorted(_slots(by_id[current])):
            for child in _slots(by_id[current])[slot]:
                if child in retained_ids:
                    frontier.append(child)
                else:
                    visit(child)

    visit(node_id)
    return frontier


def _topological_evacuation_order(
    frontier: list[str], result_tree: "_Tree"
) -> list[str]:
    frontier_ids = set(frontier)
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise TreeDiffError("result contains an evacuation dependency cycle")
        visiting.add(node_id)
        target_parent = result_tree.parent[node_id][0]
        if target_parent in frontier_ids:
            visit(target_parent)
        visiting.remove(node_id)
        visited.add(node_id)
        ordered.append(node_id)

    for node_id in frontier:
        visit(node_id)
    return ordered


def _direct_evacuation_location(
    bot: dict[str, Any], node_id: str, result_tree: "_Tree"
) -> dict[str, Any] | None:
    parent_id, slot, desired_index = result_tree.parent[node_id]
    if parent_id is not None:
        parent = _nodes_by_id(bot).get(parent_id)
        if parent is None or slot not in _slots(parent):
            return None
        if parent_id in _draft_descendants(bot, node_id):
            return None
    target = _target(bot, parent_id, slot)
    return {
        "parentId": parent_id,
        "slot": slot,
        "index": min(desired_index, len(target)),
    }


def _remove_subtree(bot: dict[str, Any], node_id: str) -> None:
    by_id = _nodes_by_id(bot)
    removed: set[str] = set()

    def visit(current: str) -> None:
        if current in removed:
            return
        removed.add(current)
        for children in _slots(by_id[current]).values():
            for child in children:
                visit(child)

    visit(node_id)
    parent_id, slot, _ = _placement(bot, node_id)
    _target(bot, parent_id, slot).remove(node_id)
    bot["flow"]["nodes"] = [
        node for node in bot["flow"]["nodes"] if node["id"] not in removed
    ]


class _Tree:
    def __init__(self, bot: dict[str, Any], *, label: str) -> None:
        if not isinstance(bot, dict):
            raise TreeDiffError(f"{label} bot must be an object")
        flow = bot.get("flow")
        if (
            not isinstance(flow, dict)
            or not isinstance(flow.get("root"), list)
            or not all(isinstance(node_id, str) for node_id in flow["root"])
            or not isinstance(flow.get("nodes"), list)
        ):
            raise TreeDiffError(f"{label} bot has an invalid flow")
        self.by_id: dict[str, dict[str, Any]] = {}
        for node in flow["nodes"]:
            if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                raise TreeDiffError(f"{label} bot contains an invalid node")
            if node["id"] in self.by_id:
                raise TreeDiffError(f"{label} bot contains duplicate node IDs")
            if not isinstance(node.get("type"), str) or not isinstance(node.get("params"), dict):
                raise TreeDiffError(f"{label} bot contains invalid node data")
            _slots(node)
            self.by_id[node["id"]] = node

        self.parent: dict[str, tuple[str | None, str, int]] = {}
        self.containers: list[tuple[str | None, str, list[str]]] = []
        self.preorder: list[str] = []
        visiting: set[str] = set()

        def visit_sequence(
            ids: list[str], parent_id: str | None, slot: str
        ) -> None:
            self.containers.append((parent_id, slot, list(ids)))
            for index, node_id in enumerate(ids):
                if node_id not in self.by_id:
                    raise TreeDiffError(f"{label} placement references an unknown node")
                if node_id in self.parent:
                    raise TreeDiffError(f"{label} node is placed more than once")
                if node_id in visiting:
                    raise TreeDiffError(f"{label} bot contains a cycle")
                self.parent[node_id] = (parent_id, slot, index)
                self.preorder.append(node_id)
                visiting.add(node_id)
                for child_slot in sorted(_slots(self.by_id[node_id])):
                    visit_sequence(
                        _slots(self.by_id[node_id])[child_slot], node_id, child_slot
                    )
                visiting.remove(node_id)

        visit_sequence(flow["root"], None, "root")
        if set(self.parent) != set(self.by_id):
            raise TreeDiffError(f"{label} bot contains unplaced nodes")

    def descendants(self, node_id: str) -> set[str]:
        found: set[str] = set()
        pending = [node_id]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            for children in _slots(self.by_id[current]).values():
                pending.extend(children)
        return found
