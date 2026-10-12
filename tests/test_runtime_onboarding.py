from pathlib import Path
from app.config import get_settings
from app.services.market_service import MarketService
from app.services.data_source_service import DataSourceService
from app.services.onboarding_service import OnboardingService
from app.repositories.semantic_repository import SemanticRepository
from app.services.graph_rag_service import GraphRAGService
from app.services.relationship_service import RelationshipService
from app.services.description_service import DescriptionService


def test_no_bundled_customer_market_packages():
    root=get_settings().data_dir/'semantic'/'markets'
    assert list(root.glob('*/market.yaml'))==[]


def test_seed_ontology_is_empty_scaffold():
    d=SemanticRepository().seed.joinpath('ontology.json').read_text()
    assert 'data_dictionary' in d
    assert 'customers' not in d and 'orders' not in d


def test_real_source_is_configured_and_discoverable():
    svc=DataSourceService(); src={x['id']:x for x in svc.sources()}
    assert src['postgres']['configured'] is True
    d=svc.discover('postgres',['main'])
    assert d['sample_rows_used'] is False
    assert {x['table'] for x in d['objects']}=={'customers','orders'}


def test_runtime_workspace_exists_only_after_onboarding():
    rows=MarketService().list_markets(); assert any(x['id']=='test-lab' for x in rows)
    ctx=MarketService().context('test-lab')
    assert ctx['market']['data_source']=='postgres'
    assert 'orders' in ctx['concepts']
    assert ctx['metrics']
    assert all((m or {}).get('status')=='inferred' for m in ctx['metrics'].values())
    assert 'orders_record_count' in ctx['metrics'] and 'sum_orders_amount' in ctx['metrics']


def test_generated_yaml_mirror_is_in_state_not_packaged_data():
    p=get_settings().state_dir/'semantic'/'workspaces'/'test-lab'
    assert (p/'market.yaml').exists() and (p/'bindings.yaml').exists() and (p/'GENERATED.md').exists()
    assert not (get_settings().data_dir/'semantic'/'markets'/'test-lab').exists()


def test_ontology_is_generated_from_metadata():
    dd=SemanticRepository().ontology()['data_dictionary']
    assert 'main' in dd and {'orders','customers'} <= set(dd['main'])
    assert dd['main']['orders']['market']=='test-lab'
    assert len(dd['main']['orders']['columns'])==5


def test_metric_candidates_are_materialized_as_inferred_metrics_and_review_queue_items():
    from app.repositories.control_repository import ControlRepository
    rows=[x for x in ControlRepository().list('SUGGESTION',500) if x.get('market')=='test-lab' and x.get('type')=='metric_candidate']
    assert rows
    assert all(x['status']=='inferred' for x in rows)
    metrics=MarketService().context('test-lab')['metrics']
    assert metrics and all((m or {}).get('status')=='inferred' for m in metrics.values())
    assert any((m or {}).get('aggregation')=='count_distinct' for m in metrics.values())


def test_relationship_candidates_are_blocked_until_review():
    rows=[x for x in RelationshipService().all() if x.get('market')=='test-lab']
    assert rows
    assert all(not x['trusted_for_queries'] for x in rows if x['status']=='ai_suggested')


def test_graph_builds_from_runtime_metadata():
    g=GraphRAGService().build('test-lab',persist=False)
    assert g['version']=='3.0'
    assert g['stats']['node_types']['table']==2
    assert g['stats']['node_types']['column']>=9
    assert g['stats']['candidate_join_edges']>=1


def test_description_generation_uses_no_sample_rows():
    d=DescriptionService().generate('test-lab','main','orders','status')
    assert d['description']
    assert d['sample_data_required'] is False
    assert d['evidence']['sample_values'] is False


def test_resync_keeps_workspace_runtime_generated():
    d=OnboardingService().sync_catalog('test-lab',['main'])
    assert d['workspace_id']=='test-lab'
    assert d['sample_rows_used'] is False
