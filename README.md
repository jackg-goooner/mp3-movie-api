# MP3 Movie API

This FastAPI application uploads and processes one movie collection, with SQLite keeping the current data across server restarts. `main.py` exposes health, upload, retrieval, SQL search, and processing endpoints, while `src/database.py` manages the SQLite schema and `src/storage.py` performs transactional writes and parameterized SQL queries. The upload endpoint accepts CSV files containing exactly `title`, `release_year`, `rating`, and `genre`, then replaces the stored collection. The processing endpoint reuses the MP1 validation and cleaning pipeline and saves its result as the new collection. `src/cache.py` caches only `GET /movies` responses for 90 seconds, and successful uploads and processing invalidate all cached limits. Request IDs and application logs are provided by the middleware and utilities in `src/`.

Start the API from this directory with:

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Run the required tests with:

```bash
python -m pytest tests -v
```

Example processing request:

```bash
curl -X POST http://127.0.0.1:8000/movies/process \
  -H 'Content-Type: application/json' \
  -d '{"validation":{"required_columns":["title","release_year","rating","genre"],"numeric_columns":["release_year","rating"]},"processing":{"remove_duplicates":true,"missing":{"enabled":true,"axis":"rows"},"outliers":{"enabled":true,"columns":["rating"],"method":"iqr","threshold":1.5}}}'
```

For `fixtures/sample_movies.csv`, the expected report has `validation_rows_removed: 0` and a cleaning report with 20 rows before, 16 rows after, 4 rows removed, and all 4 columns retained.
