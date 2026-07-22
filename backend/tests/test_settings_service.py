from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.services import settings_service as service_module
from app.services.settings_service import SECRET_MASK, SettingsService


def _svc_with_db(values: dict[str, str]) -> SettingsService:
    """注入一个返回固定 DB 快照的 SettingsService。"""
    store = MagicMock()
    store.get_all.return_value = [MagicMock(key=k, value=v) for k, v in values.items()]
    return SettingsService(store=store)


def _env_settings(**overrides) -> Settings:
    """构造一个显式设置了指定字段的 Settings（模拟 .env 显式配置）。

    屏蔽真实 .env 文件与环境变量，保证 model_fields_set 只含显式传入项。
    """
    return Settings(_env_file=None, llm_api_key="test-key", **overrides)


@pytest.fixture
def empty_db_svc():
    return _svc_with_db({})


@pytest.fixture(autouse=True)
def _isolate_env_source(monkeypatch):
    """默认视为无任何显式环境配置，使 source/default 断言与真实 .env 内容无关。

    需要模拟 .env 显式配置的用例可在函数体内再次 monkeypatch 覆盖。
    """
    monkeypatch.setattr(service_module, "get_settings", lambda: _env_settings())


def test_bool_coercion():
    svc = SettingsService()
    assert svc.validate_and_coerce("auto_index_on_upload", True) == "true"
    assert svc.validate_and_coerce("auto_index_on_upload", False) == "false"
    assert svc.validate_and_coerce("auto_index_on_upload", "TRUE") == "true"
    assert svc.validate_and_coerce("auto_index_on_upload", "0") == "false"


def test_chain_db_beats_env(monkeypatch):
    """DB 覆盖优先于 .env 显式配置。"""
    monkeypatch.setattr(
        service_module, "get_settings", lambda: _env_settings(refusal_threshold=0.5)
    )
    svc = _svc_with_db({"refusal_threshold": "0.8"})
    assert svc.get_runtime_value("refusal_threshold") == 0.8


def test_chain_env_beats_default(empty_db_svc, monkeypatch):
    """无 DB 覆盖时，.env 显式配置优先于代码默认值。"""
    monkeypatch.setattr(
        service_module, "get_settings", lambda: _env_settings(refusal_threshold=0.5)
    )
    assert empty_db_svc.get_runtime_value("refusal_threshold") == 0.5


def test_chain_default_when_neither(empty_db_svc, monkeypatch):
    """DB 与 .env 都没有时，回落到代码默认值。"""
    monkeypatch.setattr(service_module, "get_settings", lambda: _env_settings())
    assert empty_db_svc.get_runtime_value("refusal_threshold") == 0.3


def test_source_detection(empty_db_svc, monkeypatch):
    monkeypatch.setattr(
        service_module, "get_settings", lambda: _env_settings(stale_threshold_days=30)
    )
    assert empty_db_svc.get_source("stale_threshold_days") == "env"
    assert empty_db_svc.get_source("refusal_threshold") == "default"
    # 缓存是进程级共享的，更换 DB 快照前必须先失效
    SettingsService.invalidate_cache()
    svc = _svc_with_db({"refusal_threshold": "0.9"})
    assert svc.get_source("refusal_threshold") == "db"


def test_vector_index_type_default():
    svc = SettingsService()
    assert svc.get_runtime_value("vector_index_type") == "IVF_FLAT"
    assert svc.get_runtime_value("shadow_index_type") == "HNSW"
    assert svc.get_runtime_value("shadow_ratio") == 0


def test_shadow_ratio_bounds():
    svc = SettingsService()
    assert svc.validate_and_coerce("shadow_ratio", 50) == "50"
    with pytest.raises(ValueError, match="不能小于"):
        svc.validate_and_coerce("shadow_ratio", -1)
    with pytest.raises(ValueError, match="不能大于"):
        svc.validate_and_coerce("shadow_ratio", 101)


def test_vector_index_type_choice():
    svc = SettingsService()
    assert svc.validate_and_coerce("vector_index_type", "HNSW") == "HNSW"
    with pytest.raises(ValueError, match="必须是"):
        svc.validate_and_coerce("vector_index_type", "FLAT")


def test_bool_runtime_default(empty_db_svc):
    assert empty_db_svc.get_runtime_value("auto_index_on_upload") is True


def test_bool_runtime_from_db():
    svc = _svc_with_db({"auto_index_on_upload": "false"})
    assert svc.get_runtime_value("auto_index_on_upload") is False


def test_bool_runtime_invalid_fallback():
    svc = _svc_with_db({"auto_index_on_upload": "not-a-bool"})
    assert svc.get_runtime_value("auto_index_on_upload") is True


def test_db_snapshot_cached_within_ttl():
    store = MagicMock()
    store.get_all.return_value = [MagicMock(key="llm_model", value="qwen-max")]
    svc = SettingsService(store=store)
    assert svc.get_runtime_value("llm_model") == "qwen-max"
    assert svc.get_runtime_value("llm_model") == "qwen-max"
    assert store.get_all.call_count == 1
    SettingsService.invalidate_cache()
    assert svc.get_runtime_value("llm_model") == "qwen-max"
    assert store.get_all.call_count == 2


def test_db_failure_falls_back_to_default():
    store = MagicMock()
    store.get_all.side_effect = RuntimeError("db down")
    svc = SettingsService(store=store)
    assert svc.get_runtime_value("refusal_threshold") == 0.3


def test_secret_items_masked_in_list_groups():
    svc = _svc_with_db({"jwt_secret_key": "super-secret"})
    groups = svc.list_groups()
    items = {item.key: item for g in groups for item in g.items}
    jwt_item = items["jwt_secret_key"]
    assert jwt_item.secret is True
    assert jwt_item.value == SECRET_MASK
    assert jwt_item.default == SECRET_MASK
    # 非密钥项不受影响
    assert items["llm_model"].value != SECRET_MASK


def test_list_groups_exposes_flags_and_source():
    svc = _svc_with_db({"embedding_model": "bge-m3"})
    groups = svc.list_groups()
    items = {item.key: item for g in groups for item in g.items}
    assert items["embedding_model"].requires_reindex is True
    assert items["embedding_model"].source == "db"
    assert items["mysql_url"].restart_required is True
    assert items["mysql_url"].secret is True
    assert items["refusal_threshold"].source == "default"


def test_update_skips_empty_secret():
    store = MagicMock()
    store.get_all.return_value = []
    store.set_many.return_value = []
    svc = SettingsService(store=store)
    svc.update({"llm_api_key": "", "jwt_secret_key": SECRET_MASK, "llm_model": "qwen-max"})
    written = store.set_many.call_args[0][0]
    assert written == {"llm_model": "qwen-max"}


def test_update_invalidates_cache():
    store = MagicMock()
    store.get_all.return_value = [MagicMock(key="llm_model", value="old-model")]
    svc = SettingsService(store=store)
    assert svc.get_runtime_value("llm_model") == "old-model"
    store.get_all.return_value = [MagicMock(key="llm_model", value="new-model")]
    # 缓存未失效时仍是旧值
    assert svc.get_runtime_value("llm_model") == "old-model"
    svc.update({"llm_model": "new-model"})
    assert svc.get_runtime_value("llm_model") == "new-model"


def test_reset_to_default_deletes_db_row():
    store = MagicMock()
    svc = SettingsService(store=store)
    svc.reset_to_default("refusal_threshold")
    store.delete.assert_called_once_with("refusal_threshold")
    with pytest.raises(ValueError, match="未知配置项"):
        svc.reset_to_default("nope")


def test_unknown_key_raises():
    svc = SettingsService()
    with pytest.raises(ValueError, match="未知配置项"):
        svc.validate_and_coerce("unknown_key", "x")


def test_get_default_reads_config_fields(empty_db_svc):
    """原先硬编码的 4 项默认值现在必须来自 config.py 字段（.env 可表达）。"""
    assert empty_db_svc.get_default("auto_index_on_upload") is True
    assert empty_db_svc.get_default("graphrag_slow_query_threshold_ms") == 500
    assert empty_db_svc.get_default("graphrag_freshness_threshold_days") == 7
    assert empty_db_svc.get_default("graphrag_min_extraction_entities") == 1


def test_max_history_rounds_zero_is_valid():
    svc = _svc_with_db({"max_history_rounds": "0"})
    assert svc.get_runtime_value("max_history_rounds") == 0


def test_model_groups_split_by_capability():
    """模型配置按大语言模型/向量模型/Reranker 模型三组展示，各带 provider 与本组凭据。"""
    svc = _svc_with_db({})
    groups = {g.group: g.items for g in svc.list_groups()}

    assert "模型接入" not in groups
    assert "模型" not in groups

    llm_keys = [i.key for i in groups["大语言模型"]]
    assert llm_keys[0] == "llm_provider"
    assert {"llm_api_key", "llm_base_url", "llm_model", "local_llm_url", "local_llm_model"} <= set(llm_keys)

    embed_keys = [i.key for i in groups["向量模型"]]
    assert embed_keys[0] == "embedding_provider"
    assert {"embedding_api_key", "embedding_base_url", "embedding_model"} <= set(embed_keys)

    rerank_keys = [i.key for i in groups["Reranker 模型"]]
    assert rerank_keys[0] == "reranker_provider"
    assert {"reranker_api_key", "rerank_base_url", "reranker_model"} <= set(rerank_keys)

    # 各组 provider 均为 dashscope/local 下拉选项
    for group, provider_key in (
        ("大语言模型", "llm_provider"),
        ("向量模型", "embedding_provider"),
        ("Reranker 模型", "reranker_provider"),
    ):
        provider = next(i for i in groups[group] if i.key == provider_key)
        assert provider.type == "choice"
        assert provider.options == ["dashscope", "local"]


def test_embedding_provider_requires_reindex_and_local_model_flagged():
    """切换向量 provider/本地模型会改变向量空间，必须标记重建索引。"""
    svc = _svc_with_db({})
    items = {item.key: item for g in svc.list_groups() for item in g.items}
    assert items["embedding_provider"].requires_reindex is True
    assert items["local_embedding_model"].requires_reindex is True
    assert items["embedding_dim"].requires_reindex is True


def test_new_credential_fields_are_secret():
    """每组独立的 API Key 出参必须脱敏。"""
    svc = _svc_with_db({})
    items = {item.key: item for g in svc.list_groups() for item in g.items}
    for key in ("llm_api_key", "embedding_api_key", "reranker_api_key", "ocr_api_key"):
        assert items[key].secret is True
        assert items[key].value == SECRET_MASK


def test_embedding_provider_runtime_default(empty_db_svc):
    assert empty_db_svc.get_runtime_value("embedding_provider") == "dashscope"
