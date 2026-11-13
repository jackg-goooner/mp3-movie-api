import main


def test_movies_persist(client, test_storage, uploaded_movies):
    reopened = type(test_storage)(test_storage.db_path)
    movies = reopened.get()
    assert reopened.count_movies() == 20
    assert list(movies.columns) == ["title", "release_year", "rating", "genre"]
    expected_titles = ["Movie A", "Movie B", "Movie B", "Movie C", "Movie D", "Movie D"] + [
        f"Movie {letter}" for letter in "EFGHIJKLMNOPQR"
    ]
    assert movies["title"].tolist() == expected_titles

    persisted_ids = [row["id"] for row in reopened.select_columns(["title"], limit=100)]
    response = client.get("/movies?limit=100")
    assert response.status_code == 200
    retrieved_ids = [row["id"] for row in response.json()["data"]]
    assert persisted_ids == retrieved_ids == list(range(1, 21))


def test_cache_and_processing(client, uploaded_movies, processing_body):
    first = client.get("/movies?limit=100")
    second_limit = client.get("/movies?limit=1")
    assert first.status_code == second_limit.status_code == 200
    assert main.cache.get(100) == first.json()
    assert main.cache.get(1) == second_limit.json()

    repeated = client.get("/movies?limit=100")
    assert repeated.status_code == 200
    assert repeated.json() == first.json()

    processed = client.post("/movies/process", json=processing_body)
    assert processed.status_code == 200
    report = processed.json()
    assert report["validation_rows_removed"] == 0
    assert report["cleaning_report"] == {
        "rows_before": 20,
        "rows_after": 16,
        "rows_removed": 4,
        "columns_before": 4,
        "columns_after": 4,
        "columns_removed": 0,
    }
    assert main.cache.get(100) is None
    assert main.cache.get(1) is None

    refreshed = client.get("/movies?limit=100")
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["total_rows"] == 16
    assert [row["title"] for row in payload["data"]] == [f"Movie {letter}" for letter in "ABCDEFGHIJKLMNOP"]
    assert [row["id"] for row in payload["data"]] == list(range(1, 17))
    assert main.cache.get(100) == payload


def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    first = client.get("/movies?limit=100")
    assert first.status_code == 200

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Database should not be queried on a cache hit")

    monkeypatch.setattr(main.storage, "select_columns", fail_if_called)
    monkeypatch.setattr(main.storage, "count_movies", fail_if_called)
    repeated = client.get("/movies?limit=100")
    assert repeated.status_code == 200
    assert repeated.json() == first.json()


def test_search_and_upload_replaces_collection(client, sample_csv_bytes):
    upload = client.post(
        "/upload",
        files={"file": ("sample_movies.csv", sample_csv_bytes, "text/csv")},
    )
    assert upload.status_code == 200

    search = client.get(
        "/movies/search",
        params=[("columns", "title"), ("columns", "rating"), ("min_rating", "8.5"), ("limit", "2")],
    )
    assert search.status_code == 200
    assert search.json() == [
        {"id": 4, "title": "Movie C", "rating": 9.0},
        {"id": 2, "title": "Movie B", "rating": 8.5},
    ]

    replacement = client.post(
        "/upload",
        files={"file": ("sample_movies.csv", sample_csv_bytes, "text/csv")},
    )
    assert replacement.status_code == 200
    retrieved = client.get("/movies")
    assert retrieved.status_code == 200
    assert retrieved.json()["total_rows"] == 20
    assert len(retrieved.json()["data"]) == 20
