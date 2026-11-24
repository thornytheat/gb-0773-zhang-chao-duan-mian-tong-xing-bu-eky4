from app.clock import depth
from app.config import TIER_LIMIT
from app.errors import TideError

FIELDS = ('tier', 'draft_m', 'air_m', 'bridge_m')


def validate_tiers(payload):
    if not isinstance(payload, list) or not 1 <= len(payload) <= TIER_LIMIT:
        raise TideError('BAD_TIERS', f'装载档位须为 1 至 {TIER_LIMIT} 档')
    tiers, names, previous = [], set(), None
    for index, row in enumerate(payload, 1):
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise TideError('BAD_TIERS', '各档须含档位、吃水、水上船高、桥底标高')
        name = str(row['tier']).strip()
        try:
            draft, air, bridge = (depth(str(row[key])) for key in ('draft_m', 'air_m', 'bridge_m'))
            if not name or len(name) > 20 or name in names or min(draft, air, bridge) <= 0:
                raise ValueError()
            if previous is not None and not (draft < previous[0] and air > previous[1]):
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise TideError('BAD_TIERS', f'第 {index} 档定义错误：档位须唯一，吃水逐档递减，水上船高逐档递增') from exc
        names.add(name)
        previous = (draft, air)
        tiers.append({'tier': name, 'draft_m': str(draft), 'air_m': str(air), 'bridge_m': str(bridge)})
    return tiers
