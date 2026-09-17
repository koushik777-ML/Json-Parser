import re
import json
from typing import Any, Dict, List, Set, Tuple, Optional
from deepdiff import DeepDiff
from core.database import get_collection_direct
from core.schemas import (
    AnalyzePathResponse,
    CategoryItem,
    ChartData,
    DocumentMetricItem,
    OverallMetricsSummary,
    PathValuesSummary,
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

def _comparison_forms(value: str) -> Set[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower().replace("&", " and ")).strip()
    compact = normalized.replace(" ", "")
    return {compact}

def is_partial(old: Any, new: Any) -> bool:
    if not isinstance(old, str) or not isinstance(new, str):
        return False
    old_clean = old.lower().strip()
    new_clean = new.lower().strip()
    if not old_clean or not new_clean:
        return False
    old_forms = _comparison_forms(old_clean)
    new_forms = _comparison_forms(new_clean)
    if old_clean == new_clean:
        return False
    return any(
        old_form == new_form
        or (
            not (old_form + "s" == new_form or new_form + "s" == old_form)
            and (old_form in new_form or new_form in old_form)
        )
        for old_form in old_forms
        for new_form in new_forms
    )


def find_partial_matches(
    old_extracted: List[Tuple[str, Any]],
    new_extracted: List[Tuple[str, Any]]
) -> List[Dict[str, Any]]:
    old_values: Dict[str, str] = {}
    old_paths: Dict[str, str] = {}
    new_values: Dict[str, str] = {}
    new_paths: Dict[str, str] = {}

    for actual_path, value in old_extracted:
        if isinstance(value, str) and not is_empty(value):
            normalized = value.strip().lower()
            if normalized and normalized != "nan":
                old_values.setdefault(normalized, normalized)
                old_paths.setdefault(normalized, actual_path)

    for actual_path, value in new_extracted:
        if isinstance(value, str) and not is_empty(value):
            normalized = value.strip().lower()
            if normalized and normalized != "nan":
                new_values.setdefault(normalized, normalized)
                new_paths.setdefault(normalized, actual_path)

    matched_old: Set[str] = set()
    candidates = [
        (abs(len(old_value) - len(new_value)), old_value, new_value)
        for old_value in old_values
        for new_value in new_values
        if old_value not in new_values
        and new_value not in old_values
        and is_partial(old_value, new_value)
    ]

    matches = []
    for _, old_value, new_value in sorted(candidates):
        if old_value in matched_old:
            continue
        matched_old.add(old_value)
        matches.append({
            "old": old_values[old_value],
            "new": new_values[new_value],
            "old_path": old_paths[old_value],
            "new_path": new_paths[new_value],
        })

    return matches

def normalize_path(path: str) -> str:
    return re.sub(r"\[\d+\]", "[*]", path)

def discover_paths(data: Any, max_depth: int = 5) -> Set[str]:
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


def compute_path_values_comparison(
    documents: List[Dict[str, Any]],
    path: str
) -> Tuple[PathValuesSummary, Dict[str, Dict[str, Any]]]:
    global_v1_set: Set[str] = set()
    global_v3_set: Set[str] = set()
    doc_values_map: Dict[str, Dict[str, Any]] = {}

    for doc in documents:
        doc_id = str(doc["_id"])
        v1 = _parser_json(doc, "v5")
        v3 = _parser_json(doc, "v7")

        v1_extracted = walk_json_path(v1, path)
        v3_extracted = walk_json_path(v3, path)

        doc_v1: Set[str] = set()
        for _, val in v1_extracted:
            if not is_empty(val):
                s = str(val).strip().lower()
                if s and s != "nan":
                    doc_v1.add(s)

        doc_v3: Set[str] = set()
        for _, val in v3_extracted:
            if not is_empty(val):
                s = str(val).strip().lower()
                if s and s != "nan":
                    doc_v3.add(s)

        doc_common = sorted(list(doc_v1 & doc_v3))
        doc_added = sorted(list(doc_v3 - doc_v1))
        doc_removed = sorted(list(doc_v1 - doc_v3))

        global_v1_set.update(doc_v1)
        global_v3_set.update(doc_v3)

        doc_values_map[doc_id] = {
            "v1_values": sorted(list(doc_v1)),
            "v3_values": sorted(list(doc_v3)),
            "common": doc_common,
            "added": doc_added,
            "removed": doc_removed,
        }

    global_v1 = sorted(list(global_v1_set))
    global_v3 = sorted(list(global_v3_set))
    global_common = sorted(list(global_v1_set & global_v3_set))
    global_added = sorted(list(global_v3_set - global_v1_set))
    global_removed = sorted(list(global_v1_set - global_v3_set))

    summary = PathValuesSummary(
        path=path,
        total_v1_values_count=len(global_v1),
        total_v3_values_count=len(global_v3),
        common_values_count=len(global_common),
        added_values_count=len(global_added),
        removed_values_count=len(global_removed),
        v1_values=global_v1,
        v3_values=global_v3,
        common_values=global_common,
        added_values=global_added,
        removed_values=global_removed,
    )
    return summary, doc_values_map


def _parser_json(document: Dict[str, Any], version: str) -> Any:
    value = document.get(version)
    if value is not None:
        if isinstance(value, dict) and "parserJson" in value:
            return value.get("parserJson", {})
        return value

    legacy_key = "parserResponseV1" if version == "v5" else "parserResponseV3"
    return document.get(legacy_key, {}).get("parserJson", {})


class ParserAnalyticsService:

    @staticmethod
    def fetch_documents(mongo_uri: str, database: str, collection: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        col = get_collection_direct(mongo_uri, database, collection)
        query = col.find({}, {"_id": 1, "v5": 1, "v7": 1, "parserResponseV1": 1, "parserResponseV3": 1})
        if limit and limit > 0:
            query = query.limit(limit)
        
        docs = []
        for doc in query:
            docs.append({
                "_id": str(doc["_id"]),
                "v5": doc.get("v5") or doc.get("parserResponseV1", {}),
                "v7": doc.get("v7") or doc.get("parserResponseV3", {})
            })
        return docs

    @staticmethod
    def extract_suggested_paths(sample_docs: List[Dict[str, Any]]) -> List[str]:
        all_paths = set()
        for doc in sample_docs:
            v1_json = _parser_json(doc, "v5")
            v3_json = _parser_json(doc, "v7")
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

        path_values_summary, doc_values_map = compute_path_values_comparison(documents, path)


        diff_collection_data: List[Dict[str, Any]] = []
        for doc in documents:
            v1 = _parser_json(doc, "v5")
            v3 = _parser_json(doc, "v7")
            
            diff = DeepDiff(v1, v3, ignore_order=False, report_repetition=True)
            diff_dict = json.loads(diff.to_json()) if diff else {}

            diff_collection_data.append({
                "document_id": doc["_id"],
                "diff": diff_dict
            })

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
            v1 = _parser_json(doc, "v5")
            v3 = _parser_json(doc, "v7")

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


        doc_metric_items: List[DocumentMetricItem] = []
        total_common_sum = 0
        total_added_sum = 0
        total_removed_sum = 0
        total_partial_sum = 0
        total_empty_sum = 0
        total_v1_sum = 0
        total_v3_sum = 0
        global_v1_values: Set[str] = set()
        globally_covered_v1_values: Set[str] = set()

        for doc in documents:
            doc_id = doc["_id"]
            items = doc_categories_map.get(doc_id, [])
            
            doc_val_info = doc_values_map.get(doc_id, {})
            v1_set = set(doc_val_info.get("v1_values", []))
            v3_set = set(doc_val_info.get("v3_values", []))
            common = doc_val_info.get("common", [])
            old_extracted = walk_json_path(_parser_json(doc, "v5"), path)
            new_extracted = walk_json_path(_parser_json(doc, "v7"), path)
            partial_matches = find_partial_matches(old_extracted, new_extracted)
            partial_old = {match["old"] for match in partial_matches}
            partial_new = {match["new"] for match in partial_matches}
            added = sorted(v3_set - v1_set - partial_new)
            removed = sorted(v1_set - v3_set - partial_old)

            partial_items = [
                {
                    "old": match["old"],
                    "new": match["new"],
                    "path": f"{match['old_path']} -> {match['new_path']}"
                }
                for match in partial_matches
            ]

            p_count = len(partial_matches)
            e_count = sum(1 for it in items if it["category"] == "empty")

            global_v1_values.update(v1_set)
            globally_covered_v1_values.update(v1_set & v3_set)
            globally_covered_v1_values.update(partial_old)

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

        v1_coverage = round(
            (len(globally_covered_v1_values) / len(global_v1_values)) * 100, 2
        ) if global_v1_values else 0.0
        summary = OverallMetricsSummary(
            total_documents=len(documents),
            total_v1_items=total_v1_sum,
            total_v3_items=total_v3_sum,
            total_common=total_common_sum,
            total_added=total_added_sum,
            total_removed=total_removed_sum,
            total_partial=total_partial_sum,
            total_empty=total_empty_sum,
            v1_coverage=v1_coverage
        )

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
            raw_categories=raw_categories[:200],  #
            path_values_summary=path_values_summary
        )
