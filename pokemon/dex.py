"""Cached bulk data from the official PokéAPI repository (all available generations)."""
import asyncio
import csv
import io
import aiohttp

BASE = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/'
TABLES = ('pokemon_species', 'pokemon', 'pokemon_stats', 'pokemon_types', 'types',
          'natures', 'moves', 'pokemon_moves', 'type_efficacy', 'pokemon_evolution')


class Dex:
    def __init__(self, path):
        self.path = path
        self.species, self.pokemon, self.natures, self.moves = {}, {}, {}, {}
        self.learnsets, self.evolutions, self.efficacy = {}, {}, {}
        self.lock = asyncio.Lock()

    async def load(self):
        async with self.lock:
            if self.species: return
            self.path.mkdir(parents=True, exist_ok=True)
            tables = {}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as session:
                for name in TABLES:
                    file = self.path / (name + '.csv')
                    if file.exists():
                        content = await asyncio.to_thread(file.read_text, encoding='utf-8')
                    else:
                        async with session.get(BASE + name + '.csv') as response:
                            response.raise_for_status()
                            content = await response.text()
                        temp = file.with_suffix('.tmp')
                        await asyncio.to_thread(temp.write_text, content, encoding='utf-8')
                        temp.replace(file)
                    tables[name] = list(csv.DictReader(io.StringIO(content)))
            staged = Dex(self.path)
            await asyncio.to_thread(staged.build, tables)
            for name in ("species", "pokemon", "natures", "moves", "learnsets", "evolutions", "efficacy"):
                setattr(self, name, getattr(staged, name))

    def build(self, tables):
        types = {int(r['id']): r['identifier'] for r in tables['types']}
        for r in tables['pokemon']:
            pid = int(r['id'])
            self.pokemon[pid] = {'id': pid, 'species': int(r['species_id']),
                'name': r['identifier'], 'height': int(r['height']), 'weight': int(r['weight']),
                'stats': [0]*6, 'effort': [0]*6, 'types': [], 'default': r['is_default'] == '1'}
        for r in tables['pokemon_stats']:
            self.pokemon[int(r['pokemon_id'])]['stats'][int(r['stat_id'])-1] = int(r['base_stat'])
        for r in tables['pokemon_stats']:
            self.pokemon[int(r['pokemon_id'])]['effort'][int(r['stat_id'])-1] = int(r['effort'])
        for r in tables['pokemon_types']:
            self.pokemon[int(r['pokemon_id'])]['types'].append(types[int(r['type_id'])])
        defaults = {p['species']: p for p in self.pokemon.values() if p['default']}
        for r in tables['pokemon_species']:
            sid = int(r['id'])
            p = defaults.get(sid)
            if p is None: continue
            self.species[sid] = {**p, 'pokemon_id': p['id'], 'id': sid,
                'name': r['identifier'], 'legendary': r['is_legendary'] == '1',
                'mythical': r['is_mythical'] == '1', 'capture_rate': int(r['capture_rate']),
                'family': int(r['evolution_chain_id']),
                'parent': int(r['evolves_from_species_id'] or 0)}
        for r in tables['natures']:
            self.natures[r['identifier']] = (int(r['increased_stat_id'])-1, int(r['decreased_stat_id'])-1)
        for r in tables['moves']:
            self.moves[int(r['id'])] = {'name': r['identifier'], 'type': types[int(r['type_id'])],
                'power': int(r['power'] or 0), 'pp': int(r['pp'] or 1),
                'accuracy': int(r['accuracy'] or 100), 'priority': int(r['priority'] or 0),
                'class': int(r['damage_class_id']), 'effect': int(r['effect_id'] or 0)}
        # Use the newest version group available for each Pokémon, with level-up moves.
        latest = {}
        for r in tables['pokemon_moves']:
            if r['pokemon_move_method_id'] != '1': continue
            pid, version = int(r['pokemon_id']), int(r['version_group_id'])
            if version > latest.get(pid, -1):
                latest[pid] = version
                self.learnsets[pid] = []
            if version == latest[pid]:
                self.learnsets[pid].append((int(r['level']), int(r['move_id'])))
        for r in tables['type_efficacy']:
            self.efficacy[(types[int(r['damage_type_id'])], types[int(r['target_type_id'])])] = int(r['damage_factor'])/100
        for r in tables['pokemon_evolution']:
            self.evolutions.setdefault(int(r['evolved_species_id']), []).append(r)

    def learned_moves(self, pid, level):
        result = []
        for required, move in sorted(self.learnsets.get(pid, [])):
            if required <= level and move not in result: result.append(move)
        return result or [165]  # Struggle for species with no available level-up moves.

    def resolve(self, text):
        text = str(text).strip().lower().replace(' ', '-')
        for species in self.species.values():
            if text in (str(species['id']), species['name']): return species
        raise ValueError('Unknown species. Use its Pokédex number or API name.')

    def children(self, sid):
        return [p for p in self.species.values() if p['parent'] == sid]
