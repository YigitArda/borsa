import inspect

from app.api import research as research_api


def test_sync_research_routes_do_not_block_event_loop():
    assert not inspect.iscoroutinefunction(research_api.run_sector_models)
    assert not inspect.iscoroutinefunction(research_api.compute_calibration)
    assert not inspect.iscoroutinefunction(research_api.run_ablation)
    assert not inspect.iscoroutinefunction(research_api.get_ablation_recommendations)
