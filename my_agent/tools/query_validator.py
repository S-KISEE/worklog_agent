from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class QueryValidatorTools:
    max_limit: int = 500

    def __post_init__(self) -> None:
        self.allowed_collections = {"worklogs", "users", "squads"}
        self.allowed_ops = {"find", "aggregate"}

        # Block anything that can execute server-side code or be unsafe
        self.blocked_keys = {"$where", "$function", "$accumulator"}

        # Your schema fields (exactly as you provided)
        self.fields = {
            "worklogs": {
                "_id",
                "createdAt",
                "isOnLeave",
                "isSaveAsDraft",
                "loggedDate",
                "reviewedAt",
                "squadId",
                "tasks",
                "userId",
                "worklogStatus",
                # optional if it exists in your real docs:
                "email",
            },
            "users": {
                "_id",
                "accountStatus",
                "assignedStatus",
                "availableSince",
                "benchStatus",
                "billable",
                "countryOfResidence",
                "createdAt",
                "department",
                "deploymentStatus",
                "designation",
                "email",
                "employeeActiveStatus",
                "employeeId",
                "employeeInvolvementStatus",
                "employeeLevel",
                "employeementType",
                "fullname",
                "gender",
                "jobType",
                "joinedDate",
                "profileId",
                "resignDate",
                "shift",
                "timezone",
                "updatedAt",
            },
            "squads": {
                "_id",
                "createdAt",
                "endDate",
                "name",
                "startDate",
                "status",
                "type",
                "updatedAt",
            },
        }

        # Allowed joined field prefixes when using aggregate with $lookup
        # Example: "user.email", "squad.name"
        self.join_prefixes = {
            "worklogs": {"user", "squad"},  # typical aliases used in pipelines
            "users": set(),
            "squads": set(),
        }

    # -------------------------
    # Utility: blocked op scan
    # -------------------------
    def _scan_blocked(self, x: Any, path: str = "$") -> Optional[Dict[str, str]]:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in self.blocked_keys:
                    return {"error_type": "unsafe_operator", "message": f"Blocked operator '{k}' at {path}"}
                child = self._scan_blocked(v, f"{path}.{k}")
                if child:
                    return child
        elif isinstance(x, list):
            for i, item in enumerate(x):
                child = self._scan_blocked(item, f"{path}[{i}]")
                if child:
                    return child
        return None

    # -------------------------
    # Field validation helpers
    # -------------------------
    def _is_allowed_field(self, collection: str, field: str) -> bool:
        """
        Allows:
          - top-level fields for the collection
          - joined aliases like user.<field> and squad.<field> for worklogs pipelines
        """
        if field in self.fields.get(collection, set()):
            return True

        # NOTE: We previously allowed dotted "user.x" here, but that is invalid for 'find'
        # operations (which this method primarily validates). Joined fields require 'aggregate'.
        # We now strictly check only the collection's own fields.
        return False

    def _validate_sort(self, collection: str, sort: Any) -> Optional[Dict[str, Any]]:
        """
        sort must be like: [["fullname", 1]] or [["loggedDate", -1]]
        """
        if sort is None:
            return None
        if not isinstance(sort, list):
            return {
                "error_type": "sort_format",
                "message": "sort must be a list of [field, direction] pairs like [[\"fullname\", 1]]",
                "example": [["loggedDate", -1]],
            }

        for idx, item in enumerate(sort):
            if not (isinstance(item, list) or isinstance(item, tuple)) or len(item) != 2:
                return {
                    "error_type": "sort_format",
                    "message": f"sort[{idx}] must be [field, direction]",
                    "example": [["loggedDate", -1]],
                }
            field, direction = item
            if not isinstance(field, str):
                return {"error_type": "sort_format", "message": f"sort[{idx}][0] must be a field string"}
            if direction not in (1, -1):
                return {"error_type": "sort_format", "message": f"sort[{idx}][1] must be 1 or -1"}
            if not self._is_allowed_field(collection, field):
                msg = f"Unknown sort field '{field}' for collection '{collection}'"
                if "." in field and (field.startswith("user.") or field.startswith("squad.")):
                     msg += ". Joined fields not supported in 'find'. Use 'aggregate'."
                return {
                    "error_type": "unknown_field",
                    "message": msg,
                    "allowed_fields": sorted(self.fields[collection]),
                }
        return None

    def _validate_projection(self, collection: str, projection: Any) -> Optional[Dict[str, Any]]:
        if projection is None:
            return None
        if not isinstance(projection, dict):
            return {
                "error_type": "projection_format",
                "message": "projection must be an object like {\"_id\":0, \"email\":1}",
            }

        for k, v in projection.items():
            if k == "_id":
                continue
            if not isinstance(v, int):
                return {
                    "error_type": "projection_format",
                    "message": f"projection field '{k}' value must be 0 or 1",
                }
            if v not in (0, 1):
                return {
                    "error_type": "projection_format",
                    "message": f"projection field '{k}' value must be 0 or 1",
                }
            if not self._is_allowed_field(collection, k):
                msg = f"Unknown projection field '{k}' for collection '{collection}'"
                if "." in k and (k.startswith("user.") or k.startswith("squad.")):
                     msg += ". Joined fields not supported in 'find'. Use 'aggregate'."
                return {
                    "error_type": "unknown_field",
                    "message": msg,
                    "allowed_fields": sorted(self.fields[collection]),
                }
        return None

    def _validate_filter_fields(self, collection: str, flt: Any) -> Optional[Dict[str, Any]]:
        """
        Minimal but useful: checks top-level keys in filter are known fields,
        except for logical operators ($and/$or/$expr) which we allow.
        """
        if not isinstance(flt, dict):
            return {"error_type": "filter_format", "message": "filter must be an object"}

        allowed_logic = {"$and", "$or", "$expr"}
        for k, v in flt.items():
            if isinstance(k, str) and k.startswith("$"):
                # allow a few logic operators, but block unsafe ones already handled
                if k not in allowed_logic:
                    return {
                        "error_type": "filter_operator",
                        "message": f"Unsupported filter operator '{k}'. Use only $and/$or/$expr at top level.",
                    }
                # recurse into list/object
                nested = self._validate_filter_fields(collection, v) if isinstance(v, dict) else None
                # if list, validate each dict
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, dict):
                            nested = self._validate_filter_fields(collection, it)
                            if nested:
                                return nested
                if nested:
                    return nested
                continue

            # normal field key
            if not isinstance(k, str):
                return {"error_type": "filter_format", "message": "filter keys must be strings"}
            if not self._is_allowed_field(collection, k):
                msg = f"Unknown filter field '{k}' for collection '{collection}'"
                if "." in k and (k.startswith("user.") or k.startswith("squad.")):
                     msg += ". Joined fields not supported in 'find'. Use 'aggregate'."
                return {
                    "error_type": "unknown_field",
                    "message": msg,
                    "allowed_fields": sorted(self.fields[collection]),
                }
        return None

    def _ensure_limit(self, spec: Dict[str, Any]) -> int:
        raw = spec.get("limit", 200)
        try:
            limit = int(raw)
        except Exception:
            limit = 200
        limit = max(1, min(limit, self.max_limit))
        spec["limit"] = limit
        return limit

    # -------------------------
    # Main validator
    # -------------------------
    def validate_query_spec(
        self,
        spec: Optional[Dict[str, Any]] = None,
        # Flattened alternatives for LLM ease-of-use
        collection: Optional[str] = None,
        operation: Optional[str] = None,
        filter: Optional[Dict[str, Any]] = None,
        pipeline: Optional[List[Dict[str, Any]]] = None,
        projection: Optional[Dict[str, Any]] = None,
        sort: Optional[List[Any]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Validates a MongoDB query spec.
        Can be called with a single 'spec' object OR with flattened arguments.
        """
        # 1. If spec is missing, try to build it from flattened args
        if spec is None:
            # If explicit collection/operation provided, build spec 
            # (check collection/operation specifically as checks)
            if collection or operation:
                spec = {
                    "collection": collection,
                    "operation": operation,
                    "limit": limit if limit is not None else 200,
                }
                if filter is not None:
                    spec["filter"] = filter
                if pipeline is not None:
                    spec["pipeline"] = pipeline
                if projection is not None:
                    spec["projection"] = projection
                if sort is not None:
                    spec["sort"] = sort
            else:
                return {
                    "ok": False,
                    "error_type": "missing_argument",
                    "message": "Missing required argument: spec (or collection/operation flattened args). Provide a MongoDB query spec.",
                    "hints": {
                        "example_find": {
                            "collection": "users",
                            "operation": "find",
                            "filter": {"fullname": {"$regex": "name", "$options": "i"}},
                            "projection": {"_id": 1, "fullname": 1, "email": 1},
                            "sort": [["fullname", 1]],
                            "limit": 50
                        }
                    }
                }
        # shape
        if not isinstance(spec, dict):
            return {
                "ok": False,
                "error_type": "shape",
                "message": "Spec must be a JSON object",
                "hints": {"expected_keys": ["collection", "operation", "limit", "filter|pipeline"]},
            }

        # blocked ops anywhere (defense in depth)
        blocked = self._scan_blocked(spec)
        if blocked:
            return {"ok": False, **blocked}

        collection = spec.get("collection")
        operation = spec.get("operation")

        if collection not in self.allowed_collections:
            return {
                "ok": False,
                "error_type": "collection",
                "message": f"Invalid collection '{collection}'. Allowed: {sorted(self.allowed_collections)}",
                "hints": {"allowed_collections": sorted(self.allowed_collections)},
            }

        if operation not in self.allowed_ops:
            return {
                "ok": False,
                "error_type": "operation",
                "message": f"Invalid operation '{operation}'. Allowed: {sorted(self.allowed_ops)}",
                "hints": {"allowed_operations": sorted(self.allowed_ops)},
            }

        limit = self._ensure_limit(spec)

        # FIND validation
        if operation == "find":
            spec.setdefault("filter", {})
            spec.setdefault("projection", {"_id": 0})
            spec.setdefault("sort", [["loggedDate", -1]])

            # Validate filter keys
            err = self._validate_filter_fields(collection, spec["filter"])
            if err:
                return {"ok": False, **err}

            # Validate projection keys
            err = self._validate_projection(collection, spec.get("projection"))
            if err:
                return {"ok": False, **err}

            # Validate sort format + fields
            err = self._validate_sort(collection, spec.get("sort"))
            if err:
                return {"ok": False, **err}

            # Enforce limit (already done)
            spec["limit"] = limit

            return {"ok": True, "spec": spec}

        # AGGREGATE validation
        if operation == "aggregate":
            pipeline = spec.get("pipeline")
            if not isinstance(pipeline, list):
                return {
                    "ok": False,
                    "error_type": "pipeline",
                    "message": "Aggregate spec requires 'pipeline' as a list",
                    "hints": {"example": [{"$match": {}}, {"$limit": limit}]},
                }

            # Ensure $limit exists
            has_limit = any(isinstance(stage, dict) and "$limit" in stage for stage in pipeline)
            if not has_limit:
                pipeline.append({"$limit": limit})
                spec["pipeline"] = pipeline

            # (Optional) You can enforce stage structure more strictly here if you want.

            return {"ok": True, "spec": spec}

        # Shouldn’t reach (operation already checked)
        return {
            "ok": False,
            "error_type": "operation",
            "message": f"Invalid operation '{operation}'",
        }
