from unittest.mock import AsyncMock, MagicMock

import pytest

from app.stores.graph_store import GraphStore


class AsyncIterator:
    def __init__(self, seq):
        self.iter = iter(seq)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def mock_driver():
    driver = MagicMock()
    session = AsyncMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=None)

    key_order = [
        "deleted_relations",
        "updated_relations",
        "deleted_entities",
        "updated_entities",
    ]

    async def _run_side_effect(query, params=None):
        for key in key_order:
            if key in query:
                return AsyncIterator([{key: 1}])
        return AsyncIterator([{"count": 1}])

    session.run = AsyncMock(side_effect=_run_side_effect)
    return driver, session


@pytest.mark.asyncio
async def test_delete_entities_and_relations_by_doc_requires_doc_id():
    store = GraphStore(driver=MagicMock())
    store._driver = MagicMock()
    result = await store.delete_entities_and_relations_by_doc("kb_1", "")
    assert result == {
        "deleted_relations": 0,
        "updated_relations": 0,
        "deleted_entities": 0,
        "updated_entities": 0,
    }


@pytest.mark.asyncio
async def test_delete_entities_and_relations_by_doc_uses_parameterized_cypher(mock_driver):
    driver, session = mock_driver
    store = GraphStore(driver=driver)

    await store.delete_entities_and_relations_by_doc("kb_1", "kb/dir_1/file.md")

    calls = session.run.call_args_list
    assert len(calls) == 4

    # 所有查询都应包含 kb_id 与 doc_id 参数化
    for call in calls:
        params = call.args[1]
        assert "kb_id" in params
        assert params["kb_id"] == "kb_1"
        assert "doc_id" in params
        assert params["doc_id"] == "kb/dir_1/file.md"


@pytest.mark.asyncio
async def test_delete_entities_and_relations_by_doc_raises_when_driver_unavailable():
    store = GraphStore(driver=None)
    with pytest.raises(Exception):
        await store.delete_entities_and_relations_by_doc("kb_1", "doc.md")
