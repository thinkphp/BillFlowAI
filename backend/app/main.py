import io
import logging
from contextlib import asynccontextmanager

import pymupdf
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import InvoiceRecord
from app.schemas import (
    GeminiInvoiceExtraction,
    InvoiceFields,
    InvoiceResponse,
    InvoiceUpdate,
)
from app.services.extractor import (
    ExtractionFailed,
    ExtractionUnavailable,
    extract_invoice,
)
from app.services.validation import validate_invoice


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="BillFlowAI", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def invoice_response(record: InvoiceRecord) -> InvoiceResponse:
    return InvoiceResponse(
        id=record.id,
        filename=record.filename,
        status=record.status,
        data=record.data,
        confidence=record.confidence,
        uncertain_fields=record.uncertain_fields,
        validation_errors=record.validation_errors,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def persist_validation(record: InvoiceRecord, data: InvoiceFields) -> None:
    uncertain, errors = validate_invoice(data, record.confidence)
    record.data = data.model_dump(mode="json")
    record.uncertain_fields = uncertain
    record.validation_errors = errors
    record.status = "needs_review" if uncertain or errors else "validated"


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/invoices", response_model=list[InvoiceResponse])
def list_invoices(db: Session = Depends(get_db)):
    records = db.scalars(select(InvoiceRecord).order_by(InvoiceRecord.created_at.desc())).all()
    return [invoice_response(record) for record in records]


@app.post(
    "/api/invoices",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_invoice(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    filename = (file.filename or "factura.pdf").replace("\\", "/").split("/")[-1]
    if not filename.lower().endswith(".pdf") or file.content_type not in (
        "application/pdf",
        "application/octet-stream",
    ):
        raise HTTPException(status_code=415, detail="Upload a PDF file.")

    content = await file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"The file exceeds the {settings.max_upload_size_mb} MB limit.",
        )
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="The file is not a valid PDF.")
    try:
        document = pymupdf.open(stream=io.BytesIO(content), filetype="pdf")
        text = "\n".join(page.get_text() for page in document)
        document.close()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The PDF could not be read.") from exc
    try:
        extraction: GeminiInvoiceExtraction = await run_in_threadpool(
            extract_invoice, text, content
        )
    except ExtractionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExtractionFailed as exc:
        headers = {"Retry-After": "5"} if exc.status_code == 503 else None
        raise HTTPException(
            status_code=exc.status_code, detail=str(exc), headers=headers
        ) from exc

    record = InvoiceRecord(
        filename=filename,
        data=extraction.model_dump(
            mode="json", exclude={"field_confidence"}
        ),
        confidence=extraction.field_confidence.model_dump(exclude_none=True),
        uncertain_fields=[],
        validation_errors=[],
    )
    persist_validation(record, InvoiceFields.model_validate(record.data))
    db.add(record)
    db.commit()
    db.refresh(record)
    return invoice_response(record)


@app.get("/api/invoices/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    record = db.get(InvoiceRecord, invoice_id)
    if not record:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice_response(record)


@app.patch("/api/invoices/{invoice_id}", response_model=InvoiceResponse)
def update_invoice(
    invoice_id: int, update: InvoiceUpdate, db: Session = Depends(get_db)
):
    record = db.get(InvoiceRecord, invoice_id)
    if not record:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    values = {**record.data, **update.model_dump(exclude_unset=True, mode="json")}
    data = InvoiceFields.model_validate(values)
    confidence = dict(record.confidence)
    for field in update.model_fields_set:
        if field in record.uncertain_fields:
            confidence[field] = 1.0
    record.confidence = confidence
    persist_validation(record, data)
    db.commit()
    db.refresh(record)
    return invoice_response(record)
