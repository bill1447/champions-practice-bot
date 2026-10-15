"""Seal public-only match-plan diagnostics for retained positions, without outcomes."""

import gzip
import hashlib
import json
from pathlib import Path

from champions_practice.agent_v2 import PublicCatalog
from champions_practice.strategic_diagnostic import diagnose_match
from tactical_consequences_evaluation import blueprints


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(gzip.decompress((ROOT/path).read_bytes()))


def preview_view(opening, own_text):
    """Roster-only reconstruction, not a retained live preview or lead observation."""
    team = []
    for chunk in own_text.strip().split('\n\n'):
        lines = chunk.splitlines()
        name, _, item = lines[0].partition(' @ ')
        team.append({'species': name.removesuffix(' (M)').removesuffix(' (F)'),
            'item': item, 'ability': next((s[9:] for s in lines if s.startswith('Ability: ')), ''),
            'moves': [s[2:] for s in lines if s.startswith('- ')],
            'hp_percent': 100, 'fainted': False, 'active': False})
    return {'turn': 0, 'phase': 'team-preview-reconstruction',
        'field': {'terrain': None, 'weather': None, 'pseudo_weather': []},
        'player': {'team': team, 'active_details': [], 'side_conditions': []},
        'opponent': {'preview_species': opening['opponent']['preview_species'],
            'active': [], 'revealed': [], 'side_conditions': []}}


def main():
    catalog = PublicCatalog.load(ROOT)
    texts, _ = blueprints()
    sources = ('runs/v2-consequences/one-turn/games.json.gz',
               'runs/v2-coverage/unfamiliar-v1/games.json.gz')
    archives = {p: read(p) for p in sources}
    checkpoints = json.loads((ROOT/'runs/v2-coverage/midgame-v1/positions.json').read_text())['cases']
    records = []
    for game in archives[sources[0]]['games']:
        # Selection uses fixed case IDs, never the winner or recommended action.
        opening = game['rows'][0]['view']
        preview = preview_view(opening, texts[game['own_team']])
        initial = diagnose_match(preview, catalog)
        records.append({'case': game['pair'], 'preview_kind': 'roster-only reconstruction',
            'preview': initial, 'opening': diagnose_match(opening, catalog, previous=initial)})
    for checkpoint in checkpoints:
        game = next(g for g in archives[checkpoint['archive']]['games'] if g['id'] == checkpoint['game'])
        previous = None
        updates = []
        for row in game['rows'][:checkpoint['checkpoint']+1]:
            previous = diagnose_match(row['view'], catalog, previous=previous)
            updates.append(previous)
        records.append({'case': checkpoint['id'], 'checkpoint': checkpoint['checkpoint'],
            'updates': updates})
    report = {'scope': 'Diagnostic only: 24 reconstructed previews/openings and 12 existing midgame checkpoints. Public views and known own roster only; no winners, actual replies, native snapshots or tactical rankings passed to the planner.',
        'catalog_fingerprint': catalog.fingerprint,
        'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
            (*sources, 'runs/v2-coverage/midgame-v1/positions.json',
             'src/champions_practice/strategic_diagnostic.py', 'scripts/strategic_diagnostic_review.py')},
        'records': records}
    output = ROOT/'runs/v2-strategic-diagnostic/v1'
    output.mkdir(parents=True, exist_ok=True)
    (output/'plans.json').write_text(json.dumps(report, indent=2)+'\n')
    excerpts = []
    for record in records:
        plan = record.get('opening') or record['updates'][-1]
        excerpts.append({'case': record['case'], 'turn': plan['turn'], 'anchor': plan['anchor'],
            'update': plan['update'], 'requirements': plan['requirements'],
            'blockers': plan['blockers'], 'opponent_plans': plan['opponent_plans'],
            'available_answers': plan['available_answers']})
    review = {k: v for k, v in report.items() if k != 'records'}
    review.update(plans_archive_sha256=hashlib.sha256((output/'plans.json').read_bytes()).hexdigest(),
                  records=excerpts)
    (ROOT/'reviews/v2-strategic-diagnostic-2026-10-15.json').write_text(json.dumps(review, indent=2)+'\n')
    print('Sealed', len(records), 'diagnostic records')
    for record in excerpts:
        print(record['case'], record['turn'], record['anchor'], record['update'])


if __name__ == '__main__':
    main()
