"""FastAPI application for a persistent, cache-aware movie collection."""

import io
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from data_pipeline import create_cleaning_report, process_data, validate_dataframe
from src import (
    HealthResponse,
    MovieCache,
    MovieDataResponse,
    MovieProcessingReport,
    MovieStorage,
    MovieUploadInfo,
    ProcessConfig,
    log_requests,
    setup_logging,
)
from src.storage import MOVIE_COLUMNS

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Movie Data API", version="1.0.0")
app.middleware("http")(log_requests)
storage = MovieStorage()
cache = MovieCache()


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return HealthResponse(status="ok", version="1.0.0")


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Validate and replace the current collection with an uploaded CSV."""
    filename = file.filename or ""
    if Path(filename).suffix.lower() != ".csv":
        logger.warning("Unsupported file format: %s", Path(filename).suffix or "<none>")
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        logger.warning("Could not parse uploaded CSV %s: %s", filename, exc)
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a readable CSV.",
        ) from exc

    if len(df.columns) != len(MOVIE_COLUMNS) or set(df.columns) != set(MOVIE_COLUMNS):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain exactly these columns: {', '.join(MOVIE_COLUMNS)}.",
        )
    if df.empty:
        raise HTTPException(status_code=400, detail="CSV must contain at least one movie.")

    df = df[MOVIE_COLUMNS]
    storage.save(df)
    cache.invalidate()
    logger.info("Uploaded movies: filename=%s, rows=%s", filename, len(df))
    return MovieUploadInfo(
        filename=filename,
        rows=len(df),
        columns=len(df.columns),
        column_names=MOVIE_COLUMNS,
    )


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return cached or persisted movies, with the full collection size."""
    cached = cache.get(limit)
    if cached is not None:
        logger.info("Movie cache hit: limit=%s", limit)
        return cached

    records = storage.select_columns(MOVIE_COLUMNS, limit=limit)
    total_rows = storage.count_movies()
    response = {"data": records, "total_rows": total_rows}
    cache.set(limit, response)
    logger.info("Retrieved movies: returned_rows=%s", len(records))
    return response


@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1),
):
    """Search movies using a minimum rating and requested result fields."""
    try:
        results = storage.query_movies(columns, min_rating, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(
        "Queried movies: columns=%s, min_rating=%s, returned_rows=%s",
        columns,
        min_rating,
        len(results),
    )
    return results


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and clean the current collection, then replace it."""
    df = storage.get()
    if df.empty:
        raise HTTPException(status_code=400, detail="No movies are available to process.")

    config_dict = config.model_dump()
    numeric_columns = config_dict["validation"]["numeric_columns"]
    missing_numeric_columns = [column for column in numeric_columns if column not in df.columns]
    if missing_numeric_columns:
        detail = f"Numeric column is missing: {missing_numeric_columns[0]}"
        logger.warning("Movie processing rejected: %s", detail)
        raise HTTPException(status_code=400, detail=detail)

    try:
        validated_df = validate_dataframe(
            df,
            required_columns=config_dict["validation"]["required_columns"],
            numeric_columns=numeric_columns,
        )
        validation_rows_removed = len(df) - len(validated_df)
        validated_copy = validated_df.copy(deep=True)
        processed_df = process_data(validated_df, config_dict)
        cleaning_report = create_cleaning_report(validated_copy, processed_df)
    except ValueError as exc:
        logger.warning("Movie processing rejected: error=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage.save(processed_df)
    cache.invalidate()
    logger.info(
        "Processed movies: validation_removed=%s, rows_before=%s, rows_after=%s",
        validation_rows_removed,
        cleaning_report["rows_before"],
        cleaning_report["rows_after"],
    )
    return {
        "validation_rows_removed": validation_rows_removed,
        "cleaning_report": cleaning_report,
    }
