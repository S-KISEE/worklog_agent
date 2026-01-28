# my_agent/tools/mongo_executor.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from pymongo import MongoClient
from bson import ObjectId


@dataclass
class MongoExecutorTools:
    """
    Executes a VALIDATED MongoDB query spec and returns results in JSON-safe form.

    Spec format (expected):
      FIND:
        {
          "collection": "worklogs"|"users"|"squads",
          "operation": "find",
          "filter": {...},
          "projection": {...},
          "sort": [["loggedDate", -1]],
          "limit": 200
        }

      AGGREGATE:
        {
          "collection": "worklogs"|"users"|"squads",
          "operation": "aggregate",
          "pipeline": [...],
          "limit": 200
        }

    Notes:
    - The tool accepts Extended JSON inputs such as {"$date": "..."} and {"$oid":"..."}
      and converts them into Python datetime/ObjectId for PyMongo execution.
    - The tool converts outputs (ObjectId/datetime) into JSON-safe strings.
    """

    client: MongoClient
    db_name: str
    max_limit: int = 500

    def __post_init__(self) -> None:
        self.db = self.client[self.db_name]
        self.allowed_collections = {"worklogs", "users", "squads"}

        # Extra safety (even if you validate elsewhere)
        self.blocked_keys = {"$where", "$function", "$accumulator"}

    # -----------------------------
    # Helpers: input conversions
    # -----------------------------
    def _iso_to_dt_utc(self, iso_str: str) -> datetime:
        s = iso_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _convert_extended_json_inputs(self, obj: Any) -> Any:
        """
        Convert common Extended JSON objects:
          {"$date": "<iso>"} -> datetime (UTC)
          {"$oid": "<hex>"}  -> ObjectId
        Recursively walks dict/list.
        """
        if isinstance(obj, dict):
            # {"$date": "..."}
            if set(obj.keys()) == {"$date"} and isinstance(obj["$date"], str):
                return self._iso_to_dt_utc(obj["$date"])

            # {"$oid": "..."}
            if set(obj.keys()) == {"$oid"} and isinstance(obj["$oid"], str):
                try:
                    return ObjectId(obj["$oid"])
                except Exception:
                    # Keep as-is; validator should prevent invalid ObjectId usage.
                    return obj

            return {k: self._convert_extended_json_inputs(v) for k, v in obj.items()}

        if isinstance(obj, list):
            return [self._convert_extended_json_inputs(x) for x in obj]

        return obj

    def _contains_blocked_ops(self, obj: Any) -> Optional[str]:
        """
        Returns an error string if blocked keys found anywhere, else None.
        """
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in self.blocked_keys:
                    return f"Blocked operator used: {k}"
                msg = self._contains_blocked_ops(v)
                if msg:
                    return msg
        elif isinstance(obj, list):
            for item in obj:
                msg = self._contains_blocked_ops(item)
                if msg:
                    return msg
        return None

    # -----------------------------
    # Helpers: output conversions
    # -----------------------------
    def _json_safe(self, obj: Any) -> Any:
        """
        Convert PyMongo-returned objects into JSON-serializable values.
        - ObjectId -> str
        - datetime -> ISO string (UTC)
        - bytes -> base64-ish safe representation (hex)
        Recursively walks dict/list.
        """
        if isinstance(obj, ObjectId):
            return str(obj)

        if isinstance(obj, datetime):
            dt = obj
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
            return dt.isoformat().replace("+00:00", "Z")

        if isinstance(obj, bytes):
            return obj.hex()

        if isinstance(obj, dict):
            return {k: self._json_safe(v) for k, v in obj.items()}

        if isinstance(obj, list):
            return [self._json_safe(x) for x in obj]

        return obj

    # -----------------------------
    # Main executor
    # -----------------------------
    def run_query(
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
        Execute a validated spec and return JSON results (or error JSON).
        Can be called with 'spec' or flattened args.
        """
        if spec is None:
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
                    "error_type": "missing_argument",
                    "exception": "ValueError",
                    "message": "Missing required argument: spec",
                    "count": 0,
                    "records": []
                }
        if not isinstance(spec, dict):
            return {
                "error_type": "executor_input",
                "exception": "TypeError",
                "message": "spec must be a JSON object",
                "count": 0,
                "records": [],
            }

        # Safety scan for blocked ops (defense in depth)
        blocked_msg = self._contains_blocked_ops(spec)
        if blocked_msg:
            return {
                "error_type": "unsafe_operator",
                "exception": "ValueError",
                "message": blocked_msg,
                "count": 0,
                "records": [],
            }

        collection_name = spec.get("collection")
        operation = spec.get("operation")

        if collection_name not in self.allowed_collections:
            return {
                "error_type": "executor_input",
                "exception": "ValueError",
                "message": f"Invalid collection '{collection_name}'",
                "count": 0,
                "records": [],
            }

        limit_raw = spec.get("limit", 200)
        try:
            limit = int(limit_raw)
        except Exception:
            limit = 200
        limit = max(1, min(limit, self.max_limit))

        coll = self.db[collection_name]

        try:
            if operation == "find":
                flt = self._convert_extended_json_inputs(spec.get("filter", {}))
                proj = spec.get("projection", {"_id": 0})
                sort = spec.get("sort", [["loggedDate", -1]])

                cursor = coll.find(flt, proj)
                if sort:
                    # sort should be like [["field", -1], ["field2", 1]]
                    cursor = cursor.sort(sort)

                docs = list(cursor.limit(limit))
                docs = self._json_safe(docs)

                return {
                    "collection": collection_name,
                    "operation": "find",
                    "count": len(docs),
                    "records": docs,
                }

            if operation == "aggregate":
                pipeline = self._convert_extended_json_inputs(spec.get("pipeline", []))
                if not isinstance(pipeline, list):
                    return {
                        "error_type": "executor_input",
                        "exception": "TypeError",
                        "message": "pipeline must be a list",
                        "count": 0,
                        "records": [],
                    }

                # Ensure bounded (even if validator already did)
                if not any(isinstance(stage, dict) and "$limit" in stage for stage in pipeline):
                    pipeline.append({"$limit": limit})

                docs = list(coll.aggregate(pipeline, allowDiskUse=True))
                docs = docs[:limit]  # extra cap
                docs = self._json_safe(docs)

                return {
                    "collection": collection_name,
                    "operation": "aggregate",
                    "count": len(docs),
                    "records": docs,
                }

            return {
                "error_type": "executor_input",
                "exception": "ValueError",
                "message": f"Invalid operation '{operation}'",
                "count": 0,
                "records": [],
            }

        except Exception as e:
            return {
                "error_type": "mongo_runtime",
                "exception": type(e).__name__,
                "message": str(e),
                "count": 0,
                "records": [],
            }
