from typing import Any, List, Optional, Dict
from pydantic import BaseModel, Field

"""This module defines Pydantic models for request and response schemas used in the application."""
class MongoConnectionRequest(BaseModel):
    mongo_uri: str = Field(..., description="MongoDB connection URI")
    database: str = Field(..., description="Database name")
    collection: str = Field(..., description="Collection name")

class MongoConnectionResponse(BaseModel):
    status: str
    database: str
    collection: str
    databases: Optional[List[str]] = None
    collections: Optional[List[str]] = None
    total_documents: Optional[int] = None

class DocumentPreviewRequest(BaseModel):
    mongo_uri: str = Field(..., description="MongoDB connection URI")
    database: str = Field(..., description="Database name")
    collection: str = Field(..., description="Collection name")
    sample_size: int = Field(default=5, ge=1, le=50)
    
"""limits the number of sample documents to retrieve, must be between 1 and 50"""
class DocumentPreviewResponse(BaseModel):
    total_count: int
    sample_documents: List[Dict[str, Any]]
    suggested_paths: List[str]

class AnalyzePathRequest(BaseModel):
    mongo_uri: str = Field(..., description="MongoDB connection URI")
    database: str = Field(..., description="Database name")
    collection: str = Field(..., description="Collection name")
    path: str = Field(..., description="Target JSON path pattern, e.g. root['details']['locations'][*]['text']")
    limit: Optional[int] = Field(default=None, description="Optional limit on number of documents to process")

class DocumentMetricItem(BaseModel):
    document_id: str
    v1_count: int
    v3_count: int
    common_count: int
    added_count: int
    removed_count: int
    partial_count: int
    common: List[str]
    added: List[str]
    removed: List[str]
    partial: List[Dict[str, Any]] = []

class OverallMetricsSummary(BaseModel):
    total_documents: int
    total_v1_items: int
    total_v3_items: int
    total_common: int
    total_added: int
    total_removed: int
    total_partial: int
    total_empty: int
    macro_precision: float
    macro_recall: float
    macro_f1: float
    jaccard_similarity: float

class CategoryItem(BaseModel):
    category: str
    document_id: str
    path: str
    old_value: Any
    new_value: Any

class ChartData(BaseModel):
    categories_distribution: Dict[str, int]
    top_added_tokens: List[Dict[str, Any]]
    top_removed_tokens: List[Dict[str, Any]]
    top_common_tokens: List[Dict[str, Any]]
    doc_changes_distribution: Dict[str, int]

class AnalyzePathResponse(BaseModel):
    status: str
    path: str
    summary: OverallMetricsSummary
    chart_data: ChartData
    documents: List[DocumentMetricItem]
    raw_categories: Optional[List[CategoryItem]] = None
