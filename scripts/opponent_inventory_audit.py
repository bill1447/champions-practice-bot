"""Explain retained inventory admission failures using public history only.

No gate changes, native reconstruction, hidden sets or future observations.
Decision counts overlap when a position contains several inventory events.
"""

import argparse
from collections import Counter
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path

from champions_practice.competitive_evaluation import canonical_view
from champions_practice.current_state_constraints import PublicConstraintLedger
from champions_practice.diversity_league import catalog as public_priors
from champions_practice.persistent_support import public_support_contract
from champions_practice.public_lifecycle import ordered_public_lifecycle


def audit(report):
    def ident(value):
        return ''.join(c for c in str(value).lower() if c.isalnum())
    item_catalog = {ident(species): sorted({ident(candidate.item) for candidate in candidates})
                    for species, candidates in public_priors().items()}
    positions, unique = [], {}
    for game in report['games']:
        if game['version'] != 'native':
            continue
        ledger = None
        for index, row in enumerate(game['rows']):
            view = canonical_view(row['view'], game['side'])
            ledger = PublicConstraintLedger.from_public_view(view) if ledger is None else ledger.advance(view)
            if row['decision']['reason'] != 'unsupported-persistent:opponent-inventory':
                continue
            ordered = ordered_public_lifecycle(view, ledger)
            assert ordered is not None
            events = []
            for ordinal, (turn, event, actors) in enumerate(ordered):
                if event[0] not in {'-item', '-enditem'} or not event[1].startswith('p1'):
                    continue
                entry = {'turn': turn, 'event': event, 'species_at_event': actors.get(event[1]),
                         'ordinal': ordinal}
                assert entry['species_at_event'] is not None
                entry['source_item_in_approved_species_priors'] = ident(event[2]) in item_catalog.get(
                    ident(entry['species_at_event']), [])
                events.append(entry)
                unique[game['id'], ordinal] = entry
            assert events, 'inventory gate without public inventory evidence'
            contract = public_support_contract(view, ledger)
            unresolved = [asdict(m) for m in contract.mechanics if m.classification == 'unresolved']
            assert any(m['mechanic'] == 'opponent-inventory' for m in unresolved)
            positions.append({'game': game['id'], 'checkpoint': index, 'turn': row['turn'],
                'phase': row['phase'], 'hidden_family_label': game['hidden_family'],
                'events': events, 'unresolved_public_contract': unresolved,
                'current_public_opponent': view['opponent'],
                'only_public_contract_family': {m['mechanic'] for m in unresolved} == {'opponent-inventory'}})
    return {'positions': positions, 'approved_item_catalog': item_catalog, 'summary': {
        'inventory_fallback_decisions': len(positions),
        'games_affected': len({p['game'] for p in positions}),
        'distinct_public_events': len(unique),
        'distinct_events_by_kind_item': dict(Counter(e['event'][0]+':'+e['event'][2] for e in unique.values())),
        'affected_decisions_by_kind_item': dict(Counter(key for p in positions for key in
            {e['event'][0]+':'+e['event'][2] for e in p['events']})),
        'other_unresolved_public_families': dict(Counter(key for p in positions for key in
            {m['mechanic'] for m in p['unresolved_public_contract']} - {'opponent-inventory'})),
        'inventory_only_public_contract_decisions': sum(p['only_public_contract_family'] for p in positions),
        'decisions_with_source_item_outside_species_priors': sum(
            any(not e['source_item_in_approved_species_priors'] for e in p['events']) for p in positions),
        'decisions_with_all_source_items_represented': sum(
            all(e['source_item_in_approved_species_priors'] for e in p['events']) for p in positions),
        'turns': dict(Counter(p['turn'] for p in positions))},
        'limitations': ['This diagnoses recorded first-reported inventory fallbacks, not all inventory-blocked positions.',
            'Public contract checks do not replace static-prior, field, native restoration or positive-admission checks.',
            'Inventory-only public contract does not imply the position would be admitted after a fix.',
            'Repeated observations of one event are counted once per game in distinct-event totals.',
            'No support gate, action score or recorded decision was changed.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.archive.read_bytes()
    report = audit(json.loads(gzip.decompress(raw)))
    report['archive_sha256'] = hashlib.sha256(raw).hexdigest()
    report['source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
