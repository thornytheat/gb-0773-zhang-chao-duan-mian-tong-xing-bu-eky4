from fractions import Fraction

from app.config import BRIDGE_SECTION, SHALLOW_SECTION
from app.errors import TideError

from .checks import Checkpoint, judge, span_windows

CODES = {'FULL_NOW': '本潮满装出发', 'REDUCED_NOW': '本潮减载出发',
         'WAIT_NEXT': '等下一潮满装', 'NO_EVIDENCE': '缺证待补测'}


def build_advice(sections, order, tiers):
    for name in (SHALLOW_SECTION, BRIDGE_SECTION):
        if name not in sections:
            raise TideError('NO_SECTION', f'站点表缺少{name}断面', 409)
    start, end = order['start'], order['end']
    rows, clocks = [], []
    for tier in tiers:
        draft, air, bridge = (Fraction(tier[key]) for key in ('draft_m', 'air_m', 'bridge_m'))
        checkpoints = [Checkpoint('shallow', SHALLOW_SECTION, sections[SHALLOW_SECTION], draft),
                       Checkpoint('bridge', BRIDGE_SECTION, sections[BRIDGE_SECTION], bridge - air, bridge)]
        pieces, windows, isolated = span_windows(checkpoints, start, end)
        seconds = dict.fromkeys(('open', 'blocked', 'unknown'), Fraction(0))
        for piece in pieces:
            seconds[piece['status']] += Fraction(piece['seconds'])
        clocks.append(checkpoints)
        rows.append({**tier, 'pieces': pieces, 'windows': windows, 'isolated_points': isolated,
                     'seconds': {key: str(value) for key, value in seconds.items()}})
    recommendation = recommend(rows)
    if recommendation['depart_at'] is not None:
        picked = next(index for index, row in enumerate(rows) if row['tier'] == recommendation['tier'])
        departure = Fraction(recommendation['depart_at'])
        recommendation['evidence'] = judge(clocks[picked], departure)['evidence']
    return {'vessel': order['vessel'], 'window': {'start': str(start), 'end': str(end)},
            'route': {'shallow': SHALLOW_SECTION, 'bridge': BRIDGE_SECTION},
            'tiers': rows, 'recommendation': recommendation}


def recommend(rows):
    for index, row in enumerate(rows):
        if row['windows']:
            code = 'FULL_NOW' if index == 0 else 'REDUCED_NOW'
            return {'code': code, 'tier': row['tier'], 'depart_at': row['windows'][0]['start'],
                    'text': CODES[code]}
    code = 'NO_EVIDENCE' if any(Fraction(row['seconds']['unknown']) > 0 for row in rows) else 'WAIT_NEXT'
    return {'code': code, 'tier': None, 'depart_at': None, 'text': CODES[code]}
