from concurrent.futures import ThreadPoolExecutor

from gambit.infrastructure.storage import Store

def test_cached_evidence_has_one_publisher_and_survives_restart(tmp_path,) -> None:
    path = str(tmp_path / "evidence.sqlite3",)
    store = Store(path,)

    with ThreadPoolExecutor(max_workers=4,) as executor:
        results = list(executor.map(
            lambda index: store.put_analysis_cache(
                "fingerprint",
                {"id": str(index,), "value": 7,},
            ),
            range(8,),
        ),)

    assert len({result["id"] for result in results},) == 1
    assert store.count_records("analysis",) == 1
    store.close()
    restored = Store(path,)

    try:
        assert restored.get_analysis_cache("fingerprint",) == results[0]
        assert restored.get_analysis_cache("different fingerprint",) is None
    finally:
        restored.close()
