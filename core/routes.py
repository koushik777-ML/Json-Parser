import csv
import io
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pymongo.errors import PyMongoError

from core.database import verify_connection
from core.schemas import (
    AnalyzePathRequest,
    AnalyzePathResponse,
    DocumentPreviewRequest,
    DocumentPreviewResponse,
    MongoConnectionRequest,
    MongoConnectionResponse,
)
from core.services import ParserAnalyticsService

router = APIRouter(prefix="/api")

@router.post("/connect", response_model=MongoConnectionResponse, status_code=status.HTTP_200_OK)
def connect(connection: MongoConnectionRequest):
    try:
        total_docs, dbs, cols = verify_connection(
            mongo_uri=connection.mongo_uri,
            database_name=connection.database,
            collection_name=connection.collection
        )
        return MongoConnectionResponse(
            status="connected",
            database=connection.database,
            collection=connection.collection,
            databases=dbs,
            collections=cols,
            total_documents=total_docs
        )
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"MongoDB connection failed: {exc}"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected connection error: {exc}"
        )

@router.post("/preview", response_model=DocumentPreviewResponse, status_code=status.HTTP_200_OK)
def preview_collection(req: DocumentPreviewRequest):
    try:
        sample_docs = ParserAnalyticsService.fetch_documents(
            mongo_uri=req.mongo_uri,
            database=req.database,
            collection=req.collection,
            limit=req.sample_size
        )
        suggested_paths = ParserAnalyticsService.extract_suggested_paths(sample_docs)
        
        total_docs, _, _ = verify_connection(
            mongo_uri=req.mongo_uri,
            database_name=req.database,
            collection_name=req.collection
        )

        return DocumentPreviewResponse(
            total_count=total_docs,
            sample_documents=sample_docs,
            suggested_paths=suggested_paths
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch preview: {exc}"
        )

@router.post("/analyze", response_model=AnalyzePathResponse, status_code=status.HTTP_200_OK)
def analyze_path_endpoint(req: AnalyzePathRequest):
    try:
        response = ParserAnalyticsService.analyze_pipeline(
            mongo_uri=req.mongo_uri,
            database=req.database,
            collection=req.collection,
            path=req.path,
            limit=req.limit
        )
        return response
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {exc}"
        )

@router.post("/export/csv",include_in_schema=False)
def export_csv(req: AnalyzePathRequest):
    try:
        response = ParserAnalyticsService.analyze_pipeline(
            mongo_uri=req.mongo_uri,
            database=req.database,
            collection=req.collection,
            path=req.path,
            limit=req.limit
        )
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            "document_id",
            "v1_count",
            "v3_count",
            "common_count",
            "added_count",
            "removed_count",
            "partial_count",
            "common_tokens",
            "added_tokens",
            "removed_tokens"
        ])
        
        for doc in response.documents:
            writer.writerow([
                doc.document_id,
                doc.v1_count,
                doc.v3_count,
                doc.common_count,
                doc.added_count,
                doc.removed_count,
                doc.partial_count,
                "; ".join(doc.common),
                "; ".join(doc.added),
                "; ".join(doc.removed)
            ])
            
        output.seek(0)
        filename = f"parser_metrics_{req.collection}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Export failed: {exc}"
        )