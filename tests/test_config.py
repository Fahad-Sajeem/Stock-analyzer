from analyzer.config import get_config, load_config


def test_config_loads():
    cfg = get_config()
    assert cfg.risk.get("capital", 0) > 0
    assert cfg.tradability.min_price == 20.0
    assert cfg.ingestion.nse_base_url.startswith("https://")


def test_weights_sum_validated():
    cfg = load_config()
    # composite weights must sum to 1.0 (validated at load)
    assert abs(sum(cfg.signals["composite_weights"].values()) - 1.0) < 1e-9
    # quality weights must sum to 100
    assert abs(sum(cfg.fundamentals["quality_weights"].values()) - 100) < 1e-9


def test_path_helpers_absolute():
    cfg = get_config()
    assert cfg.db_path.is_absolute()
    assert cfg.charts_path.is_absolute()
