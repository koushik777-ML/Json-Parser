import re
import json
from collections import Counter
from typing import Any, Dict, List, Set, Tuple, Optional
from deepdiff import DeepDiff
from core.database import get_collection_direct
from core.schemas import (
    AnalyzePathResponse,
    CategoryItem,
    ChartData,
    DocumentMetricItem,
    OverallMetricsSummary,
)

def walk_json_path(data: Any, path: str) -> List[Tuple[str, Any]]:
    """
    Extracts (actual_path, value) tuples matching the path pattern like root['details']['locations'][*]['text'].
    """
    parts = re.findall(r"\['([^']+)'\]|\[(\d+|\*)\]", path)
    results = []

    def walk(value: Any, pos: int, current_path: str):
        if pos == len(parts):
            results.append((current_path, value))
            return
        key, index = parts[pos]
        if index:
            if index == "*":
                if not isinstance(value, list):
                    return
                for i, item in enumerate(value):
                    walk(item, pos + 1, current_path + f"[{i}]")
            else:
                if not isinstance(value, list):
                    return
                i = int(index)
                if i >= len(value):
                    return
                walk(value[i], pos + 1, current_path + f"[{i}]")
        else:
            if not isinstance(value, dict):
                return
            if key not in value:
                return
            walk(value[key], pos + 1, current_path + f"['{key}']")

    walk(data, 0, "root")
    return results

def is_empty(value: Any) -> bool:
    return value in (None, "", [], {})

def is_partial(old: Any, new: Any) -> bool:
    if not isinstance(old, str) or not isinstance(new, str):
        return False
    old_clean = old.lower().strip()
    new_clean = new.lower().strip()
    if not old_clean or not new_clean:
        return False
    return old_clean != new_clean and (old_clean in new_clean or new_clean in old_clean)

def normalize_path(path: str) -> str:
    return re.sub(r"\[\d+\]", "[*]", path)

def discover_paths(data: Any, max_depth: int = 5) -> Set[str]:
    """Recursively discovers distinct wildcard JSON paths in a JSON structure."""
    discovered = set()

    def traverse(val: Any, current_path: str, depth: int):
        if depth > max_depth:
            return
        if isinstance(val, dict):
            for k, v in val.items():
                p = f"{current_path}['{k}']"
                discovered.add(p)
                traverse(v, p, depth + 1)
        elif isinstance(val, list):
            if val:
                p = f"{current_path}[*]"
                discovered.add(p)
                for item in val[:3]:
                    traverse(item, p, depth + 1)

    traverse(data, "root", 0)
    return discovered

class ParserAnalyticsService:

    @staticmethod
    def fetch_documents(mongo_uri: str, database: str, collection: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        col = get_collection_direct(mongo_uri, database, collection)
        query = col.find({}, {"_id": 1, "parserResponseV1": 1, "parserResponseV3": 1})
        if limit and limit > 0:
            query = query.limit(limit)
        
        docs = []
        for doc in query:
            docs.append({
                "_id": str(doc["_id"]),
                "parserResponseV1": doc.get("parserResponseV1", {}),
                "parserResponseV3": doc.get("parserResponseV3", {})
            })
        return docs

    @staticmethod
    def extract_suggested_paths(sample_docs: List[Dict[str, Any]]) -> List[str]:
        all_paths = set()
        for doc in sample_docs:
            v1_json = doc.get("parserResponseV1", {}).get("parserJson", {})
            v3_json = doc.get("parserResponseV3", {}).get("parserJson", {})
            if isinstance(v1_json, dict):
                all_paths.update(discover_paths(v1_json))
            if isinstance(v3_json, dict):
                all_paths.update(discover_paths(v3_json))
        return sorted(list(all_paths))

    @staticmethod
    def analyze_pipeline(
        mongo_uri: str,
        database: str,
        collection: str,
        path: str,
        limit: Optional[int] = None
    ) -> AnalyzePathResponse:
        documents = ParserAnalyticsService.fetch_documents(mongo_uri, database, collection, limit)
        if not documents:
            raise ValueError(f"No documents found in collection '{collection}'.")

        # Step 1: DeepDiff in-memory computation
        diff_collection_data: List[Dict[str, Any]] = []
        for doc in documents:
            v1 = doc.get("parserResponseV1", {}).get("parserJson", {})
            v3 = doc.get("parserResponseV3", {}).get("parserJson", {})
            
            diff = DeepDiff(v1, v3, ignore_order=False, report_repetition=True)
            diff_dict = json.loads(diff.to_json()) if diff else {}

            diff_collection_data.append({
                "document_id": doc["_id"],
                "diff": diff_dict
            })

        # Step 2: Path Analysis & Categorization
        normalized_target_path = normalize_path(path)
        diff_paths_set = set()
        
        raw_categories: List[CategoryItem] = []
        doc_categories_map: Dict[str, List[Dict[str, Any]]] = {doc["_id"]: [] for doc in documents}
        
        # 2a. Check differences from DeepDiff
        for diff_entry in diff_collection_data:
            doc_id = diff_entry["document_id"]
            changes = diff_entry.get("diff", {}).get("values_changed", {})
            
            for diff_path, value in changes.items():
                if normalize_path(diff_path) != normalized_target_path:
                    continue
                old_val = value.get("old_value")
                new_val = value.get("new_value")

                diff_paths_set.add((doc_id, diff_path))
                
                cat = "changed"
                if is_empty(old_val) or is_empty(new_val):
                    if is_empty(old_val) and is_empty(new_val):
                        cat = "common"
                    else:
                        cat = "empty"
                elif is_partial(old_val, new_val):
                    cat = "partial"

                item = {
                    "category": cat,
                    "document_id": doc_id,
                    "path": diff_path,
                    "old_value": old_val,
                    "new_value": new_val
                }
                raw_categories.append(CategoryItem(**item))
                doc_categories_map[doc_id].append(item)

        # 2b. Check source collections for unchanged / common items
        for doc in documents:
            doc_id = doc["_id"]
            v1 = doc.get("parserResponseV1", {}).get("parserJson", {})
            v3 = doc.get("parserResponseV3", {}).get("parserJson", {})

            old_values = dict(walk_json_path(v1, path))
            new_values = dict(walk_json_path(v3, path))
            all_paths = set(old_values.keys()) | set(new_values.keys())

            for actual_path in all_paths:
                if (doc_id, actual_path) in diff_paths_set:
                    continue
                
                old_val = old_values.get(actual_path)
                new_val = new_values.get(actual_path)
                
                cat = "changed"
                if is_empty(old_val) and is_empty(new_val):
                    cat = "common"
                elif is_empty(old_val) or is_empty(new_val):
                    cat = "empty"
                elif old_val == new_val:
                    cat = "common"
                elif is_partial(old_val, new_val):
                    cat = "partial"

                item = {
                    "category": cat,
                    "document_id": doc_id,
                    "path": actual_path,
                    "old_value": old_val,
                    "new_value": new_val
                }
                raw_categories.append(CategoryItem(**item))
                doc_categories_map[doc_id].append(item)

        # Step 3: Metrics Computation (from final.ipynb)
        all_added_tokens = []
        all_removed_tokens = []
        all_common_tokens = []
        
        doc_metric_items: List[DocumentMetricItem] = []
        total_common_sum = 0
        total_added_sum = 0
        total_removed_sum = 0
        total_partial_sum = 0
        total_empty_sum = 0
        total_v1_sum = 0
        total_v3_sum = 0

        for doc in documents:
            doc_id = doc["_id"]
            items = doc_categories_map.get(doc_id, [])
            
            v1_set: Set[str] = set()
            v3_set: Set[str] = set()
            partial_items: List[Dict[str, Any]] = []

            for it in items:
                old_str = str(it["old_value"]).strip().lower() if not is_empty(it["old_value"]) else ""
                new_str = str(it["new_value"]).strip().lower() if not is_empty(it["new_value"]) else ""
                
                if old_str and old_str != "nan":
                    v1_set.add(old_str)
                if new_str and new_str != "nan":
                    v3_set.add(new_str)
                
                if it["category"] == "partial":
                    partial_items.append({
                        "old": it["old_value"],
                        "new": it["new_value"],
                        "path": it["path"]
                    })

            common = sorted(list(v1_set & v3_set))
            added = sorted(list(v3_set - v1_set))
            removed = sorted(list(v1_set - v3_set))
            
            p_count = sum(1 for it in items if it["category"] == "partial")
            e_count = sum(1 for it in items if it["category"] == "empty")

            all_common_tokens.extend(common)
            all_added_tokens.extend(added)
            all_removed_tokens.extend(removed)

            total_common_sum += len(common)
            total_added_sum += len(added)
            total_removed_sum += len(removed)
            total_partial_sum += p_count
            total_empty_sum += e_count
            total_v1_sum += len(v1_set)
            total_v3_sum += len(v3_set)

            doc_metric_items.append(DocumentMetricItem(
                document_id=doc_id,
                v1_count=len(v1_set),
                v3_count=len(v3_set),
                common_count=len(common),
                added_count=len(added),
                removed_count=len(removed),
                partial_count=p_count,
                common=common,
                added=added,
                removed=removed,
                partial=partial_items
            ))

        # Global aggregate calculation
        macro_precision = (
            round((total_common_sum / (total_common_sum + total_added_sum)) * 100, 2)
            if (total_common_sum + total_added_sum) > 0 else 0.0
        )
        macro_recall = (
            round((total_common_sum / (total_common_sum + total_removed_sum)) * 100, 2)
            if (total_common_sum + total_removed_sum) > 0 else 0.0
        )
        macro_f1 = (
            round((2 * (macro_precision * macro_recall) / (macro_precision + macro_recall)), 2)
            if (macro_precision + macro_recall) > 0 else 0.0
        )
        jaccard = (
            round((total_common_sum / (total_common_sum + total_added_sum + total_removed_sum)) * 100, 2)
            if (total_common_sum + total_added_sum + total_removed_sum) > 0 else 0.0
        )

        summary = OverallMetricsSummary(
            total_documents=len(documents),
            total_v1_items=total_v1_sum,
            total_v3_items=total_v3_sum,
            total_common=total_common_sum,
            total_added=total_added_sum,
            total_removed=total_removed_sum,
            total_partial=total_partial_sum,
            total_empty=total_empty_sum,
            macro_precision=macro_precision,
            macro_recall=macro_recall,
            macro_f1=macro_f1,
            jaccard_similarity=jaccard
        )

        # Top tokens for charts
        top_added = [{"token": k, "count": v} for k, v in Counter(all_added_tokens).most_common(10)]
        top_removed = [{"token": k, "count": v} for k, v in Counter(all_removed_tokens).most_common(10)]
        top_common = [{"token": k, "count": v} for k, v in Counter(all_common_tokens).most_common(10)]

        # Changes distribution per document (e.g. docs with no changes, minor changes, major changes)
        perfect_match_docs = sum(1 for d in doc_metric_items if d.added_count == 0 and d.removed_count == 0 and d.common_count > 0)
        modified_docs = sum(1 for d in doc_metric_items if d.added_count > 0 or d.removed_count > 0 or d.partial_count > 0)
        empty_docs = sum(1 for d in doc_metric_items if d.v1_count == 0 and d.v3_count == 0)

        chart_data = ChartData(
            categories_distribution={
                "Common (Unchanged)": total_common_sum,
                "Added in V3": total_added_sum,
                "Removed in V3": total_removed_sum,
                "Partial Matches": total_partial_sum,
                "Empty / Null": total_empty_sum
            },
            top_added_tokens=top_added,
            top_removed_tokens=top_removed,
            top_common_tokens=top_common,
            doc_changes_distribution={
                "100% Match": perfect_match_docs,
                "Modified": modified_docs,
                "No Data Found": empty_docs
            }
        )

        return AnalyzePathResponse(
            status="success",
            path=path,
            summary=summary,
            chart_data=chart_data,
            documents=doc_metric_items,
            raw_categories=raw_categories[:200]  # sample for inspector
        )
