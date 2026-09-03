from typing import List, Tuple
from pymongo import MongoClient
from pymongo.collection import Collection

_client_cache: dict[str, MongoClient] = {}

def get_mongo_client(mongo_uri: str) -> MongoClient:
    """Returns a cached MongoClient or creates a new tested connection."""
    if mongo_uri in _client_cache:
        try:
            _client_cache[mongo_uri].admin.command("ping")
            return _client_cache[mongo_uri]
        except Exception:
            _client_cache.pop(mongo_uri, None)
    
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    _client_cache[mongo_uri] = client
    return client

def verify_connection(mongo_uri: str, database_name: str, collection_name: str) -> Tuple[int, List[str], List[str]]:
    """Verifies connection and returns (total_docs, all_databases, all_collections)."""
    client = get_mongo_client(mongo_uri)
    dbs = client.list_database_names()
    cols = client[database_name].list_collection_names()
    total_docs = client[database_name][collection_name].count_documents({})
    return total_docs, dbs, cols

def get_collection_direct(mongo_uri: str, database_name: str, collection_name: str) -> Collection:
    client = get_mongo_client(mongo_uri)
    return client[database_name][collection_name]

