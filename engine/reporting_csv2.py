import re
from pymongo import MongoClient
import csv

client = MongoClient("mongodb://localhost:27017/")
db = client["maprecruit"]
diff_collection = db["diff"]
source_collection = db["jd3"]

def get_value(data, path):
    parts = re.findall(r"\['([^']+)'\]|\[(\d+|\*)\]",path)
    results = []

    def walk(value, pos, current_path):
        if pos == len(parts):
            results.append((current_path, value))
            return
        key, index = parts[pos]
        if index:
            if index == "*":
                if not isinstance(value, list):
                    return
                for i, item in enumerate(value):
                    walk(item,pos + 1,current_path + f"[{i}]")
            else:
                if not isinstance(value, list):
                    return
                i = int(index)
                if i >= len(value):
                    return
                walk(value[i],pos + 1,current_path + f"[{i}]")
        else:
            if not isinstance(value, dict):
                return
            if key not in value:
                return
            walk(value[key],pos + 1,current_path + f"['{key}']")
    walk(data, 0, "root")
    return results

def is_empty(value):
    return value in (None, "", [], {})

def is_partial(old, new):
    if not isinstance(old, str) or not isinstance(new, str):
        return False

    old = old.lower().strip()
    new = new.lower().strip()

    return old != new and (old in new or new in old)

def normalize_path(path):
    return re.sub(r"\[\d+\]","[*]",path)

def analyze_path(path):
    common_count = 0
    changed = []
    partials = []
    empty_values = []
    normalized_path = normalize_path(path)
    common = []

    diff_paths = set()

    for doc in diff_collection.find():
        doc_id = str(doc.get("document_id"))
        changes = (doc.get("diff", {}).get("values_changed", {}))

        for diff_path, value in changes.items():
            if normalize_path(diff_path) != normalized_path:
                continue
            old = value.get("old_value")
            new = value.get("new_value")

            item = {
                "document_id": doc_id,
                "path": diff_path,
                "old_value": old,
                "new_value": new
            }
            diff_paths.add((doc_id, diff_path))
            if is_empty(old) or is_empty(new):
                if is_empty(old) and is_empty(new):
                    common_count += 1
                else:
                    empty_values.append(item)
            elif is_partial(old, new):
                partials.append(item)
            else:
                changed.append(item)

    for doc in source_collection.find():
        doc_id = str(doc["_id"])
        v1 = (doc.get("parserResponseV1", {}).get("parserJson", {}))
        v3 = (doc.get("parserResponseV3", {}).get("parserJson", {}))

        old_values = dict(get_value(v1, path))
        new_values = dict(get_value(v3, path))
        all_paths = (set(old_values) |set(new_values))
        common_paths = (set(old_values) & set(new_values))
        for actual_path in all_paths:
            old = old_values.get(actual_path)
            new = new_values.get(actual_path)

            if (doc_id, actual_path) in diff_paths:
                continue
            item = {
                "document_id": doc_id,
                "path": actual_path,
                "old_value": old,
                "new_value": new
            }
            if is_empty(old) and is_empty(new):
                common_count += 1
                common.append(item)
            elif is_empty(old) or is_empty(new):
                empty_values.append(item)
            elif old == new:
                common_count += 1
                common.append(item)
            elif is_partial(old, new):
                partials.append(item)
            else:
                changed.append(item)

    return {
        "path": path,
        "common_count": common_count,
        "common": common,
        "changed": changed,
        "changed_count": len(changed),
        "partial": partials,
        "partial_count": len(partials),
        "empty": empty_values,
        "empty_count": len(empty_values)
    }

result = analyze_path("root['details']['locations'][*]['text']")
with open("final_overall_result_location.csv", "w", newline="", encoding="utf-8") as file:

    writer = csv.DictWriter(
        file,
        fieldnames=[
            "category",
            "document_id",
            "path",
            "old_value",
            "new_value"
        ]
    )

    writer.writeheader()

    for item in result["common"]:
        writer.writerow({
            "category": "common",
            "document_id": item["document_id"],
            "old_value": item["old_value"],
            "new_value": item["new_value"]
        })


    for item in result["changed"]:
        writer.writerow({
            "category": "changed",
            "document_id": item["document_id"],
            "old_value": item["old_value"],
            "new_value": item["new_value"]
        })

    for item in result["partial"]:
        writer.writerow({
            "category": "partial",
            "document_id": item["document_id"],
            "old_value": item["old_value"],
            "new_value": item["new_value"]
        })

    for item in result["empty"]:
        writer.writerow({
            "category": "empty",
            "document_id": item["document_id"],
            "old_value": item["old_value"],
            "new_value": item["new_value"]
        })