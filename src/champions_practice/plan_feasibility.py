"""Compare route requirements on native leaves, without selecting or scoring moves."""

from .strategic_diagnostic import diagnose_match, moves, resource_id


def compare_routes(ranking, root_view, catalog, *, side):
    plans = diagnose_match(root_view, catalog)['competing_plans']
    owned = {resource_id(m['species']): m for m in root_view['player']['team']}
    other = 'p1' if side == 'p2' else 'p2'
    comparisons = []
    for candidate in ranking:
        leaves = [leaf for world in candidate['worlds'] for sample in world['sampled_responses'].values()
                  for leaf in sample['leaf_positions']]
        assert leaves
        facts = {'action': candidate['action'], 'existing_utility': candidate['worst_world_utility'],
                 'native_leaf_samples': len(leaves), 'routes': []}
        for plan in plans:
            resource = plan['resource']
            samples = []
            for leaf in leaves:
                ours = [m for m in leaf[side]['pokemon'] if m['hp'] > 0 and not m['fainted']]
                foes = [m for m in leaf[other]['pokemon'] if m['hp'] > 0 and not m['fainted']]
                sample = {'own_remaining': len(ours), 'opponent_remaining': len(foes),
                    'terminal_win': bool(leaf['ended'] and leaf['winner'] == leaf[side]['name'])}
                if resource:
                    key = resource_id(resource)
                    living = next((m for m in ours if resource_id(m['species']) == key), None)
                    active = next((m for m in leaf[side]['active'] if m and m['hp'] > 0 and resource_id(m['species']) == key), None)
                    psychic = 'expandingforce' in moves(owned[key]) if key in owned else False
                    sample.update(resource_living=living is not None, resource_active=active is not None,
                        grounded_psychic_terrain=bool(active and active['grounded'] and leaf['field']['terrain'] == 'psychicterrain') if psychic else None)
                    mega_fairy = key == 'gardevoir' and 'hypervoice' in moves(owned[key]) and owned[key].get('item') == 'gardevoirite'
                    sample['mega_fairy_mode'] = ('evolved' if living and living['species'] == 'Gardevoir-Mega'
                        else 'available' if living and leaf.get('ownMegaAvailability', {}).get(key) is True
                        else 'unavailable') if mega_fairy else 'not-required'
                samples.append(sample)
            report = {'name': plan['name'], 'resource': resource,
                'samples': samples, 'terminal_wins': sum(s['terminal_win'] for s in samples)}
            if resource:
                report['living_samples'] = sum(s['resource_living'] for s in samples)
                report['active_samples'] = sum(s['resource_active'] for s in samples)
                report['assessment'] = 'resource absent in every sampled result' if not report['living_samples'] else 'route unresolved: living is not an attacking-window certificate'
                report['terrain_ready_samples'] = sum(s['grounded_psychic_terrain'] is True for s in samples)
                report['mega_fairy_available_or_evolved_samples'] = sum(s['mega_fairy_mode'] in {'available', 'evolved'} for s in samples)
            else:
                report['assessment'] = 'material counts and terminal outcomes only; no material-exchange utility bonus'
            facts['routes'].append(report)
        comparisons.append(facts)
    return {'plans': plans, 'comparisons': comparisons,
        'scope': 'Requirement comparison over completed native leaves. No new weights, action ranking, plan commitment, future attack or win-probability claim. Samples share worlds/responses and are correlated.'}
