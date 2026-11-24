from concurrent.futures import ThreadPoolExecutor

import pytest

from app.errors import TideError
from app.main import create_app
from app.modules.sailing.advice import build_advice
from app.modules.sailing.service import compute, confirm, file_advice, supplement
from app.modules.sailing.store import SailingBook
from app.modules.sailing.tiers import validate_tiers
from app.source import load_sources

TIERS = [
    {'tier': '满档', 'draft_m': '2.5', 'air_m': '6.2', 'bridge_m': '8.5'},
    {'tier': '减载一', 'draft_m': '2.3', 'air_m': '6.6', 'bridge_m': '8.5'},
    {'tier': '减载二', 'draft_m': '2.1', 'air_m': '7.0', 'bridge_m': '8.5'},
]
CONFLICT_ROWS = [{'station': 'U1', 'observed_at': stamp, 'level': '999', 'unit': 'cm', 'quality': 'OK'}
                 for stamp in ('2026-11-22T23:40:00+08:00', '2026-11-22T23:50:00+08:00',
                               '2026-11-23T00:00:00+08:00', '2026-11-23T00:10:00+08:00',
                               '2026-11-23T00:30:00+08:00')]


@pytest.fixture
def book(tmp_path):
    return SailingBook(tmp_path / 'sail.sqlite3')


def sections(shallow, bridge, shallow_points=None, bridge_points=None):
    sp = shallow_points if shallow_points is not None else [(0, shallow), (1100, shallow)]
    bp = bridge_points if bridge_points is not None else [(0, bridge), (1100, bridge)]
    return {
        '下游浅滩': {'offset_s': 100, 'gap_s': 1200,
                     'points': [{'time': t, 'depth_m': str(d), 'water_m': '0', 'line': i + 1}
                                for i, (t, d) in enumerate(sp)]},
        '上游外闸': {'offset_s': 0, 'gap_s': 1200,
                     'points': [{'time': t, 'depth_m': '0', 'water_m': str(w), 'line': i + 11}
                                for i, (t, w) in enumerate(bp)]},
    }


ORDER = {'vessel': '测试轮', 'line': 1, 'draft_m': '2', 'clearance_m': '0', 'threshold_m': '2',
         'start': 0, 'end': 1000, 'requested': 0}


def tier(draft, air):
    return {'tier': f'吃水{draft}', 'draft_m': str(draft), 'air_m': str(air), 'bridge_m': '10'}


def test_dirty_full_now():
    result = compute(load_sources({'sample': 'dirty'}), '海棠17', TIERS)
    recommendation = result['recommendation']
    assert recommendation['code'] == 'FULL_NOW' and recommendation['tier'] == '满档'
    assert result['tiers'][0]['seconds'] == {'open': '1500', 'blocked': '900', 'unknown': '600'}


def test_same_tier_checked_at_own_arrivals():
    result = compute(load_sources({'sample': 'dirty'}), '海棠17', TIERS)
    recommendation = result['recommendation']
    depart = int(recommendation['depart_at'])
    evidence = {row['kind']: row for row in recommendation['evidence']}
    assert int(evidence['shallow']['at']) - depart == 600
    assert int(evidence['bridge']['at']) - depart == 0
    assert evidence['shallow']['depth_m'] == '5/2' and evidence['bridge']['clearance_m'] == '7'
    assert all(row['status'] == 'open' for row in recommendation['evidence'])


def test_clean_full_window():
    result = compute(load_sources({'sample': 'clean'}), '海棠17', TIERS[:2])
    assert result['recommendation']['code'] == 'FULL_NOW'
    assert result['tiers'][0]['seconds'] == {'open': '3000', 'blocked': '0', 'unknown': '0'}


def test_reduced_now_picks_fullest_feasible():
    result = build_advice(sections(3, 3), ORDER, [tier('3.5', 6), tier('2.5', 6)])
    recommendation = result['recommendation']
    assert recommendation['code'] == 'REDUCED_NOW' and recommendation['tier'] == '吃水2.5'


def test_wait_next_when_bridge_blocks_reduced():
    result = build_advice(sections(3, 3), ORDER, [tier('3.5', 6), tier('2.5', 7.5)])
    assert result['recommendation']['code'] == 'WAIT_NEXT'
    codes = {piece['evidence'][1]['code'] for piece in result['tiers'][1]['pieces']}
    assert codes == {'UNDER_CLEARANCE'}


def test_bridge_unmeasured_is_no_evidence():
    result = build_advice(sections(3, 3, bridge_points=[]), ORDER, [tier('2.5', 6)])
    assert result['recommendation']['code'] == 'NO_EVIDENCE'
    assert result['tiers'][0]['seconds']['unknown'] == '1000'


def test_tier_rules():
    with pytest.raises(TideError):
        validate_tiers([{'tier': '甲', 'draft_m': '2.5', 'air_m': '7', 'bridge_m': '8.5'},
                        {'tier': '乙', 'draft_m': '2.6', 'air_m': '6', 'bridge_m': '8.5'}])
    with pytest.raises(TideError):
        validate_tiers([{'tier': '甲', 'draft_m': '2.5', 'air_m': '6', 'bridge_m': '8.5'}] * 2)
    with pytest.raises(TideError):
        validate_tiers([{'tier': '甲', 'draft_m': '2.5', 'air_m': '6'}])
    with pytest.raises(TideError):
        validate_tiers([{'tier': '甲', 'draft_m': '0', 'air_m': '6', 'bridge_m': '8.5'}])


def test_file_and_confirm(client):
    payload = {'sample': 'dirty', 'vessel': '海棠17', 'tiers': TIERS}
    first = client.post('/api/sailing/advice', json=payload)
    assert first.status_code == 201
    advice = first.json['advice']
    assert advice['status'] == 'pending' and advice['result']['recommendation']['code'] == 'FULL_NOW'
    again = client.post('/api/sailing/advice', json=payload)
    assert again.status_code == 200 and again.json['advice']['id'] == advice['id']
    done = client.post(f"/api/sailing/advice/{advice['id']}/confirm")
    assert done.status_code == 201 and done.json['advice']['status'] == 'confirmed'
    repeat = client.post(f"/api/sailing/advice/{advice['id']}/confirm")
    assert repeat.status_code == 200 and repeat.json['reused']


def test_file_rejects_bad_input(client):
    assert client.post('/api/sailing/advice', json={'sample': 'dirty', 'vessel': '海棠17',
                                                    'tiers': [{'tier': '甲'}]}).status_code == 422
    missing = client.post('/api/sailing/advice', json={'sample': 'dirty', 'vessel': '幽灵船', 'tiers': TIERS})
    assert (missing.status_code, missing.json['code']) == (404, 'NO_VESSEL')


def test_supplement_invalidates_and_keeps_archive(client):
    advice = client.post('/api/sailing/advice', json={'sample': 'dirty', 'vessel': '海棠17',
                                                      'tiers': TIERS}).json['advice']
    result = client.post('/api/sailing/supplement', json={'sample': 'dirty', 'rows': CONFLICT_ROWS})
    assert result.status_code == 201
    assert result.json['invalidated'] == [advice['id']]
    new_id = result.json['issued'][0]
    stale = client.get(f"/api/sailing/advice/{advice['id']}").json
    assert stale['status'] == 'stale' and stale['superseded_by'] == new_id
    assert stale['result']['recommendation']['code'] == 'FULL_NOW'  # 已留档结论仍可查
    fresh = client.get(f'/api/sailing/advice/{new_id}').json
    assert fresh['status'] == 'pending' and fresh['result']['recommendation']['code'] == 'NO_EVIDENCE'
    deny = client.post(f"/api/sailing/advice/{advice['id']}/confirm")
    assert (deny.status_code, deny.json['code']) == (409, 'ADVICE_STALE')
    assert client.post(f'/api/sailing/advice/{new_id}/confirm').status_code == 201


def test_harmless_supplement_keeps_advice(client):
    advice = client.post('/api/sailing/advice', json={'sample': 'dirty', 'vessel': '海棠17',
                                                      'tiers': TIERS}).json['advice']
    rows = [{'station': 'Z9', 'observed_at': '2026-11-23T00:40:00+08:00', 'level': '100',
             'unit': 'cm', 'quality': 'OK'}]
    result = client.post('/api/sailing/supplement', json={'sample': 'dirty', 'rows': rows}).json
    assert result['invalidated'] == [] and result['issued'] == []
    assert client.post(f"/api/sailing/advice/{advice['id']}/confirm").status_code == 201


def test_confirmed_archive_survives_supplement(client):
    advice = client.post('/api/sailing/advice', json={'sample': 'dirty', 'vessel': '海棠17',
                                                      'tiers': TIERS}).json['advice']
    client.post(f"/api/sailing/advice/{advice['id']}/confirm")
    result = client.post('/api/sailing/supplement', json={'sample': 'dirty', 'rows': CONFLICT_ROWS}).json
    assert result['invalidated'] == [] and len(result['issued']) == 1
    archived = client.get(f"/api/sailing/advice/{advice['id']}").json
    assert archived['status'] == 'confirmed' and archived['result']['recommendation']['code'] == 'FULL_NOW'


def test_supplement_validation(client):
    bad = client.post('/api/sailing/supplement', json={'sample': 'dirty', 'rows': [{'station': 'U1'}]})
    assert (bad.status_code, bad.json['code']) == (422, 'BAD_SUPPLEMENT')
    sentinel = client.post('/api/sailing/supplement', json={'sample': 'dirty', 'rows': [
        {'station': 'U1', 'observed_at': '2026-11-23T00:40:00+08:00', 'level': 'N/A',
         'unit': 'cm', 'quality': 'OK'}]})
    assert sentinel.status_code == 422


def test_missing_advice(client):
    result = client.get('/api/sailing/advice/absent')
    assert (result.status_code, result.json['code']) == (404, 'NO_ADVICE')


def test_confirm_races_supplement(tmp_path):
    for _ in range(8):
        book = SailingBook(tmp_path / 'race.sqlite3')
        advice = file_advice(book, {'sample': 'dirty', 'vessel': '海棠17', 'tiers': TIERS})['advice']
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(confirm, book, advice['id']),
                     pool.submit(supplement, book, {'sample': 'dirty', 'rows': CONFLICT_ROWS})]
            outcomes = [task.result() for task in tasks]
        confirmed = next((row for row in outcomes if isinstance(row, dict) and 'advice' in row), None)
        final = book.get_advice(advice['id'])
        if confirmed is not None:  # 确认先入账：已确认留档不受补录影响
            assert final['status'] == 'confirmed'
        else:  # 补录先入账：建议已失效，不能确认入簿
            assert final['status'] == 'stale' and final['superseded_by']
        (tmp_path / 'race.sqlite3').unlink()


def test_sailing_page(client):
    page = client.get('/desk/sailing')
    assert page.status_code == 200 and '装载档位' in page.get_data(as_text=True)
    advice = client.post('/api/sailing/advice', json={'sample': 'dirty', 'vessel': '海棠17',
                                                      'tiers': TIERS}).json['advice']
    page = client.get(f"/desk/sailing?advice={advice['id']}")
    text = page.get_data(as_text=True)
    assert '本潮满装出发' in text and '确认入簿' in text
