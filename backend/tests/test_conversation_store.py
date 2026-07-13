import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.stores.conversation import ConversationStore
from app.stores.db import Base


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def store(session_factory):
    return ConversationStore(session_factory=session_factory)


def test_create_with_user_id_and_title(store):
    cid = store.create(user_id=1, title="测试会话")
    conv = store.get_conversation(cid)
    assert conv is not None
    assert conv.user_id == 1
    assert conv.title == "测试会话"


def test_list_by_user_filters_and_orders_by_updated_at(store):
    c1 = store.create(user_id=1, title="A")
    c2 = store.create(user_id=1, title="B")
    _c3 = store.create(user_id=2, title="Other")

    store.append_message(c1, "user", "hello")
    store.update_timestamp(c1)
    store.append_message(c2, "user", "world")
    store.update_timestamp(c2)

    results = store.list_by_user(user_id=1, limit=10)
    assert len(results) == 2
    assert {r.id for r in results} == {c1, c2}


def test_update_title(store):
    cid = store.create(user_id=1)
    assert store.update_title(cid, "新标题") is True
    assert store.get_conversation(cid).title == "新标题"
    assert store.update_title("non-existent", "x") is False


def test_get_last_message(store):
    cid = store.create(user_id=1)
    store.append_message(cid, "user", "first")
    store.append_message(cid, "assistant", "second")
    last = store.get_last_message(cid)
    assert last.role == "assistant"
    assert last.content == "second"


def test_update_user_id(store):
    cid = store.create()
    assert store.get_conversation(cid).user_id is None
    assert store.update_user_id(cid, 42) is True
    assert store.get_conversation(cid).user_id == 42
