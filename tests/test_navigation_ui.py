from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'app/static/assets/app.js').read_text()
CSS=(ROOT/'app/static/assets/app.css').read_text()
def test_grouped_navigation_keeps_all_existing_routes():
    for k in ('home','ask','reports','data','semantics','operate','monitor','admin'):
        assert f"['{k}'," in JS
    for tab in ('ontology','trust','golden','job-center','enterprise-search','profile','contracts','quality','ai-models'):
        assert f"['{tab}'," in JS
    assert 'setTab(b.dataset.parent,b.dataset.tab)' in JS
    assert 'data-section' in JS and 'data-tab' in JS
    assert 'aria-current="page"' in JS and 'aria-expanded' in JS
    assert '.sidebar-nav' in CSS and '.nav-child.active' in CSS
def test_user_navigation_has_no_old_horizontal_tabs():
    assert 'class="tabs"' not in JS
    assert 'navMenu()' in JS
    assert 'aria-label="Application navigation"' in JS
def test_stage_terms_removed_from_readable_text():
    import re
    readable = re.findall(r"(?:sectionHead|toast|pill)\(['\"]([^'\"]+)['\"]", JS)
    assert not [v for v in readable if re.search(r'\bphases?\b',v,re.I)]
