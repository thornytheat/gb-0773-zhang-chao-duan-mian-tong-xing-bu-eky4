from bisect import bisect_left
from fractions import Fraction
from itertools import pairwise


class Checkpoint:
    """单一核验点：浅段水深或桥下净空，在各自到达时刻（出发 + 断面偏移）求值。"""

    def __init__(self, kind, name, section, limit, bridge_m=None):
        self.kind, self.name, self.offset = kind, name, section['offset_s']
        self.points, self.gap, self.limit = section['points'], section['gap_s'], limit
        self.bridge_m = bridge_m
        self.field = 'depth_m' if kind == 'shallow' else 'water_m'
        self.times = [point['time'] for point in self.points]

    def _value(self, moment):
        index = bisect_left(self.times, moment)
        if index < len(self.times) and self.times[index] == moment:
            return Fraction(self.points[index][self.field]), 'POINT', [self.points[index]['line']]
        if not 0 < index < len(self.times):
            return None, 'NO_BRACKET', []
        left, right = self.points[index - 1], self.points[index]
        lines = [left['line'], right['line']]
        if right['time'] - left['time'] > self.gap:
            return None, 'OVER_GAP', lines
        a, b = Fraction(left[self.field]), Fraction(right[self.field])
        value = a + (b - a) * Fraction(moment - left['time'], right['time'] - left['time'])
        return value, 'LINEAR', lines

    def at(self, departure):
        moment = departure + self.offset
        value, how, lines = self._value(moment)
        row = {'kind': self.kind, 'section': self.name, 'at': str(moment), 'lines': lines,
               'depth_m': None, 'clearance_m': None}
        if value is None:
            return {**row, 'code': how, 'status': 'unknown'}
        if self.kind == 'shallow':
            ok = value >= self.limit
            return {**row, 'depth_m': str(value), 'code': 'DEPTH_OK' if ok else 'UNDER_DEPTH',
                    'status': 'open' if ok else 'blocked'}
        ok = value <= self.limit
        return {**row, 'clearance_m': str(self.bridge_m - value),
                'code': 'CLEARANCE_OK' if ok else 'UNDER_CLEARANCE',
                'status': 'open' if ok else 'blocked'}

    def boundaries(self):
        for point in self.points:
            yield point['time'] - self.offset
        for left, right in pairwise(self.points):
            start, end = left['time'], right['time']
            if end - start > self.gap:
                continue
            a, b = Fraction(left[self.field]), Fraction(right[self.field])
            if a == b:
                continue
            cross = start + (end - start) * (self.limit - a) / (b - a)
            if start < cross < end:
                yield cross - self.offset


def judge(checkpoints, departure):
    evidence = [checkpoint.at(departure) for checkpoint in checkpoints]
    states = {row['status'] for row in evidence}
    status = next((state for state in ('blocked', 'unknown') if state in states), 'open')
    return {'at': str(departure), 'status': status, 'evidence': evidence}


def span_windows(checkpoints, start, end):
    cuts = {start, end}
    cuts.update(cut for checkpoint in checkpoints for cut in checkpoint.boundaries() if start < cut < end)
    knots = sorted(cuts)
    boundary = {t: judge(checkpoints, t) for t in knots[:-1]}
    pieces, windows, covered = [], [], set()
    for left, right in pairwise(knots):
        band = judge(checkpoints, Fraction(left + right, 2))
        pieces.append({**band, 'start': str(left), 'end': str(right), 'seconds': str(right - left)})
        if band['status'] != 'open':
            continue
        covered.update((left, right))
        left_open = boundary[left]['status'] == 'open'
        right_open = right in boundary and boundary[right]['status'] == 'open'
        if windows and windows[-1]['end'] == str(left) and left_open:
            windows[-1].update(end=str(right), end_included=right_open)
        else:
            windows.append(dict(start=str(left), end=str(right), start_included=left_open, end_included=right_open))
    isolated = [row for t, row in boundary.items() if row['status'] == 'open' and t not in covered]
    return pieces, windows, isolated
