from datetime import UTC, datetime

from app.errors import TideError
from app.flow import calculate
from app.modules.intake.contract import OBSERVATION, SENTINELS
from app.modules.journal.manifest import canonical, digest
from app.modules.schedule.orders import orders
from app.source import load_sources

from .advice import build_advice
from .tiers import validate_tiers

ROW_LIMIT = 200


def now():
    return datetime.now(UTC).isoformat(timespec='seconds')


def tide_revision(sample, observations):
    return digest(canonical([sample, observations]))


def effective_sources(book, sample, connection=None):
    sources = load_sources({'sample': sample})
    rows = book.supplements(sample, connection)
    if rows:
        extra = ''.join(','.join(row[key] for key in OBSERVATION) + '\n' for row in rows)
        sources['observations'] = sources['observations'].rstrip('\n') + '\n' + extra
    return sources


def compute(sources, vessel, tiers):
    reports = calculate(sources, 'datum')
    fleet = orders(reports['readings'])
    if vessel not in fleet:
        raise TideError('NO_VESSEL', '找不到该船期', 404)
    return build_advice(reports['datum']['sections'], fleet[vessel], tiers)


def version(sample, vessel, tiers, revision):
    return digest(canonical([sample, vessel, tiers, revision]))


def file_advice(book, payload):
    if not isinstance(payload, dict):
        raise TideError('BAD_SOURCE', '请提交样例、船期与装载档位')
    sample = payload.get('sample', 'dirty')
    tiers = validate_tiers(payload.get('tiers'))
    sources = effective_sources(book, sample)
    vessel = payload.get('vessel')
    result = compute(sources, vessel, tiers)
    revision = tide_revision(sample, sources['observations'])
    advice = {'id': version(sample, vessel, tiers, revision), 'sample': sample, 'vessel': vessel,
              'created': now(), 'tiers': tiers, 'tide_rev': revision, 'result': result,
              'status': 'pending', 'confirmed_at': None, 'superseded_by': None}
    with book.transaction() as connection:
        created = book.put(connection, advice)
        return {'advice': book.get_advice(advice['id'], connection), 'reused': not created}


def validate_rows(payload):
    if not isinstance(payload, list) or not 1 <= len(payload) <= ROW_LIMIT:
        raise TideError('BAD_SUPPLEMENT', f'补录须为 1 至 {ROW_LIMIT} 行潮尺记录')
    rows = []
    for index, row in enumerate(payload, 1):
        if not isinstance(row, dict) or set(row) != set(OBSERVATION):
            raise TideError('BAD_SUPPLEMENT', f'补录第 {index} 行字段须为 station、observed_at、level、unit、quality')
        values = {key: str(row[key]).strip() for key in OBSERVATION}
        if any(value.upper() in SENTINELS for value in values.values()):
            raise TideError('BAD_SUPPLEMENT', f'补录第 {index} 行含空值或哨兵')
        if any(any(mark in value for mark in ',"\r\n') for value in values.values()):
            raise TideError('BAD_SUPPLEMENT', f'补录第 {index} 行含非法字符')
        rows.append(values)
    return rows


def reissue(book, connection, advice, result, revision):
    follow = {'id': version(advice['sample'], advice['vessel'], advice['tiers'], revision),
              'sample': advice['sample'], 'vessel': advice['vessel'], 'created': now(),
              'tiers': advice['tiers'], 'tide_rev': revision, 'result': result,
              'status': 'pending', 'confirmed_at': None, 'superseded_by': None}
    book.put(connection, follow)
    return follow['id']


def supplement(book, payload):
    if not isinstance(payload, dict):
        raise TideError('BAD_SOURCE', '请提交补录潮尺行')
    sample = payload.get('sample', 'dirty')
    rows = validate_rows(payload.get('rows'))
    load_sources({'sample': sample})
    with book.transaction() as connection:
        seq = book.add_supplement(connection, sample, now(), rows)
        sources = effective_sources(book, sample, connection)
        revision = tide_revision(sample, sources['observations'])
        invalidated, issued = [], set()
        for status in ('pending', 'confirmed'):
            for advice in book.advices_by_status(connection, sample, status):
                result = compute(sources, advice['vessel'], advice['tiers'])
                if canonical(result) == canonical(advice['result']):
                    continue
                new_id = reissue(book, connection, advice, result, revision)
                if status == 'pending':
                    book.mark_stale(connection, advice['id'], new_id)
                    invalidated.append(advice['id'])
                issued.add(new_id)
        return {'seq': seq, 'tide_rev': revision, 'invalidated': invalidated, 'issued': sorted(issued)}


def confirm(book, advice_id):
    with book.transaction() as connection:
        advice = book.get_advice(advice_id, connection)
        if advice is None:
            raise TideError('NO_ADVICE', '未找到这份建议', 404)
        if advice['status'] == 'confirmed':
            return {'advice': advice, 'reused': True}
        if advice['status'] == 'stale':
            raise TideError('ADVICE_STALE', '该建议已被补录推翻，请确认重算版本', 409)
        sources = effective_sources(book, advice['sample'], connection)
        revision = tide_revision(advice['sample'], sources['observations'])
        if revision != advice['tide_rev']:
            result = compute(sources, advice['vessel'], advice['tiers'])
            if canonical(result) != canonical(advice['result']):
                new_id = reissue(book, connection, advice, result, revision)
                book.mark_stale(connection, advice_id, new_id)
                raise TideError('ADVICE_STALE', '先入账的补录已使该建议失效，不能确认入簿', 409)
            book.refresh_revision(connection, advice_id, revision)
        book.confirm(connection, advice_id, now())
        return {'advice': book.get_advice(advice_id, connection), 'reused': False}


def inspect(book, advice_id):
    advice = book.get_advice(advice_id)
    if advice is None:
        raise TideError('NO_ADVICE', '未找到这份建议', 404)
    return advice


def desk_context(book, sample, vessel, advice_id=None):
    advices = book.list_advices(sample)
    selected = None
    if advice_id:
        selected = book.get_advice(advice_id)
        if selected is None:
            raise TideError('NO_ADVICE', '未找到这份建议', 404)
    if selected is None:
        selected = next((row for row in advices if row['vessel'] == vessel), None)
    return {'advices': advices, 'selected': selected}
