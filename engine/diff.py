import json
from pymongo import MongoClient
from deepdiff import DeepDiff

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "maprecruit"
COLLECTION_NAME = "jd3"
OUTPUT_FILE = "jd3_diff.json"

client = MongoClient(MONGO_URI)
collection = client[DB_NAME][COLLECTION_NAME]

results = []
for index, document in enumerate(collection.find({}), start=1):

    v1 = document["parserResponseV1"]["parserJson"]
    v3 = document["parserResponseV3"]["parserJson"]

    diff = DeepDiff(v1,v3,ignore_order=False,report_repetition=True)

    results.append({
        "documents_index": index,
        "document_id": str(document["_id"]),
        "diff": json.loads(diff.to_json())
    })


with open(OUTPUT_FILE,"w",encoding="utf-8") as file:
    json.dump(results,file,indent=2,ensure_ascii=False)


client.close()


print(f"Generated: {OUTPUT_FILE}")
print(f"Documents processed: {len(results)}")