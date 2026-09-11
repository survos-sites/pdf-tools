"""Opt-in test against a running service; all other tests remain offline."""
import os
import httpx
import pytest

pytestmark = [pytest.mark.network, pytest.mark.skipif(os.getenv('PDFTOOLS_NETWORK') != '1', reason='opt-in real PDF')]


def test_soviet_life_reference():
    with httpx.Client(base_url=os.getenv('PDFTOOLS_URL', 'http://127.0.0.1:5001'), timeout=660) as client:
        response = client.post('/v1/files', json={'url':'https://www.marxists.org/history/ussr/culture/soviet-life/full-issues/1961/sim_soviet-life_1961-02_2.pdf'})
        response.raise_for_status()
        info = response.json()
        assert info['pages'] == 83
        assert info['iaIdentifier'] == 'sim_soviet-life_1961-02_2'
        base=f"/v1/files/{info['id']}/pages/64"
        assert len(client.get(base+'/words').json()['words']) == 1285
        hits = client.get(base+'/search?q=Michurinka').json()['hits']
        assert len(hits) == 2
        assert hits[0]['bboxPt'] == pytest.approx([308.16,767.302,345.5825,775.31], abs=.02)
