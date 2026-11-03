"""Preview reuse and private browser revalidation must preserve ownership checks."""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from server.jobs import compute_preview
from server.app import create_app
from server.config import Settings
from tests.test_calc import _points_project
from tests.test_server import register, new_generation


def test_preview_reuses_render_and_invalidates_on_data_or_missing_file(tmp_path):
    project = _points_project()
    (tmp_path / 'input.json').write_text(json.dumps(project))
    compute_preview(str(tmp_path))
    assert (tmp_path / 'preview' / 'ready').exists()
    from ansys_report.geometry import figures
    with patch.object(figures, 'make_preview', wraps=figures.make_preview) as render:
        compute_preview(str(tmp_path))
        render.assert_not_called()
        (tmp_path / 'preview' / 'prev_surface.png').unlink()
        compute_preview(str(tmp_path))
        assert render.call_count == 1
        project['values'][1][0] = '7.5'
        (tmp_path / 'input.json').write_text(json.dumps(project))
        compute_preview(str(tmp_path))
        assert render.call_count == 2


def test_preview_etag_still_requires_owner(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, inline_jobs=True, secret_key='t' * 32))
    owner = TestClient(app)
    register(owner)
    generation = new_generation(owner).headers['location']
    overview = owner.get(generation).text
    assert 'Есть превышения' in overview and 'замеры приняты' in overview
    assert 'id="project-overview"' in overview and 'Не заданы нагрузки' in overview
    url = generation + '/viewer.json'
    first = owner.get(url)
    assert first.status_code == 200
    assert 'private' in first.headers['cache-control']
    headers = {'If-None-Match': first.headers['etag']}
    assert owner.get(url, headers=headers).status_code == 304
    stranger = TestClient(app)
    register(stranger, 'b@example.com')
    assert stranger.get(url, headers=headers).status_code == 404
    assert TestClient(app).get(url, headers=headers).status_code == 404
