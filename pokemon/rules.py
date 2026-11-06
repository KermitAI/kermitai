"""Pure collection rules; independent of Discord and Red."""
import math
import random
import uuid

STATS = ('hp', 'attack', 'defense', 'special-attack', 'special-defense', 'speed')
PSEUDOS = {147,148,149,246,247,248,371,372,373,374,375,376,443,444,445,
           633,634,635,704,705,706,782,783,784,885,886,887,996,997,998}
BALLS = {'poke-ball': (100, 1), 'great-ball': (250, 1.5), 'ultra-ball': (500, 2),
         'master-ball': (100000, 1000), 'premier-ball': (100, 1),
         'luxury-ball': (1000, 1), 'heal-ball': (300, 1), 'net-ball': (500, 1),
         'dive-ball': (500, 1), 'nest-ball': (500, 1), 'repeat-ball': (500, 1),
         'timer-ball': (500, 1), 'quick-ball': (500, 1), 'dusk-ball': (500, 1),
         'level-ball': (500, 1), 'lure-ball': (500, 1), 'moon-ball': (500, 1),
         'friend-ball': (500, 1), 'love-ball': (500, 1), 'heavy-ball': (500, 1),
         'fast-ball': (500, 1), 'sport-ball': (500, 1), 'safari-ball': (500, 1),
         'beast-ball': (1000, .1), 'dream-ball': (500, 1), 'cherish-ball': (1000, 1),
         'feather-ball': (250, 1.5), 'wing-ball': (500, 2), 'jet-ball': (1000, 2.5),
         'leaden-ball': (500, 2), 'gigaton-ball': (1000, 2.5),
         'origin-ball': (100000, 2), 'strange-ball': (500, 1)}
ITEMS = {**{k: v[0] for k, v in BALLS.items()}, 'potion': 200,
         'super-potion': 500, 'hyper-potion': 1000, 'max-potion': 1500,
         'revive': 1500, 'max-revive': 3000, 'razz-berry': 100, 'pinap-berry': 200}


def account(state, user_id):
    player = state['players'].setdefault(str(user_id), {
        'xp': 0, 'dust': 0, 'candy': {}, 'box': {}, 'party': [],
        'items': {'poke-ball': 20}, 'receipts': [], 'last_pokestop': 0, 'pokedex': {}})
    if 'pokedex' not in player:
        # Older accounts have no capture history: recover what their box proves.
        player['pokedex'] = {}
        for pokemon in player['box'].values(): record_catch(player, pokemon)
    return player


def record_catch(player, pokemon):
    entry = player['pokedex'].setdefault(str(pokemon['species']),
        {'name': pokemon['name'], 'caught': 0, 'shiny': False})
    entry['caught'] += 1
    entry['shiny'] = entry['shiny'] or pokemon['shiny']


def bonus(state, role_ids):
    result = {'catch': 1., 'shiny': 1., 'rare': 1., 'xp': 1., 'candy': 0}
    for rid in role_ids:
        for key, value in state['roles'].get(str(rid), {}).items():
            result[key] = max(result[key], value)
    return result


def wild_allowed(species):
    return not (species['legendary'] or species['mythical'] or species['id'] in PSEUDOS)


def choose_species(species, rare=1, rng=random):
    eligible = [p for p in species.values() if wild_allowed(p)]
    if not eligible:
        raise ValueError('The Pokédex has no eligible wild Pokémon.')
    weights = [(max(1, p['capture_rate']) / 255) ** (1 / max(1, rare)) for p in eligible]
    return rng.choices(eligible, weights=weights, k=1)[0]


def new_pokemon(species, dex, shiny_multiplier=1, rng=random):
    level = rng.randint(1, 30)
    scale = max(.25, min(2, rng.gauss(1, .15)))
    moves = dex.learned_moves(species['pokemon_id'], level)
    result = {'id': uuid.uuid4().hex[:12], 'species': species['id'],
              'pokemon_id': species['pokemon_id'], 'name': species['name'],
              'level': level, 'shiny': rng.random() < min(1, shiny_multiplier / 4096),
              'ivs': [rng.randint(0, 31) for _ in STATS], 'evs': [0] * 6,
              'nature': rng.choice(list(dex.natures)), 'moves': moves[-4:],
              'height': round(species['height'] * scale / 10, 2),
              'weight': round(species['weight'] * scale ** 3 / 10, 2)}
    result['hp'] = stats(result, dex)[0]
    return result


def stats(pokemon, dex):
    base = dex.pokemon[pokemon['pokemon_id']]['stats']
    nature = dex.natures[pokemon['nature']]
    result = []
    for i, (b, iv, ev) in enumerate(zip(base, pokemon['ivs'], pokemon['evs'])):
        value = math.floor((2*b + iv + ev//4)*pokemon['level']/100)
        if i == 0:
            value = 1 if pokemon['species'] == 292 else value + pokemon['level'] + 10
        else:
            modifier = 1 if nature[0] == nature[1] else 1.1 if nature[0] == i else .9 if nature[1] == i else 1
            value = math.floor((value + 5)*modifier)
        result.append(value)
    return result


def hidden_power(ivs):
    # Cartridge bit order: HP, Atk, Def, Speed, SpA, SpD.
    values = [ivs[i] for i in (0, 1, 2, 5, 3, 4)]
    types = ('fighting','flying','poison','ground','rock','bug','ghost','steel',
             'fire','water','grass','electric','psychic','ice','dragon','dark')
    return types[sum((v & 1) << i for i, v in enumerate(values))*15//63]


def ball_multiplier(ball, pokemon, species, player, attempts):
    multiplier = BALLS[ball][1]
    types = species['types']
    if ball == 'net-ball' and set(types) & {'water', 'bug'}: multiplier = 3.5
    if ball == 'nest-ball': multiplier = max(1, (41-pokemon['level'])/10)
    if ball == 'repeat-ball' and any(p['species'] == pokemon['species'] for p in player['box'].values()): multiplier = 3.5
    if ball == 'timer-ball': multiplier = min(4, 1 + attempts*.3)
    if ball == 'quick-ball' and attempts == 0: multiplier = 5
    if ball == 'level-ball': multiplier = 2
    if ball == 'heavy-ball' and pokemon['weight'] >= 200: multiplier = 2
    if ball == 'fast-ball' and species['stats'][5] >= 100: multiplier = 4
    return multiplier


def catch_chance(ball, pokemon, species, player, perks, attempts=0, berry=None):
    if ball == 'master-ball': return 1
    rate = species['capture_rate']/255
    rate *= ball_multiplier(ball, pokemon, species, player, attempts)*perks['catch']
    if berry == 'razz-berry': rate *= 1.5
    return min(.98, max(.01, rate))


def remove_pokemon(player, pid):
    if pid not in player['box']:
        raise ValueError('That Pokémon is no longer in the box.')
    player['party'] = [p for p in player['party'] if p != pid]
    return player['box'].pop(pid)


def transfer(player, pid, family):
    remove_pokemon(player, pid)
    key = str(family)
    player['candy'][key] = player['candy'].get(key, 0) + 1


def swap(state, first, second, offer, request):
    """Validate both sides completely before any mutation. Currency uses bank separately."""
    a, b = account(state, first), account(state, second)
    if first == second: raise ValueError('Choose another trainer.')
    for owner, bundle in ((a, offer), (b, request)):
        if len(bundle['pokemon']) != len(set(bundle['pokemon'])):
            raise ValueError('A Pokémon cannot be offered twice.')
        if any(pid not in owner['box'] for pid in bundle['pokemon']):
            raise ValueError('A traded Pokémon is no longer owned by its trainer.')
        for item, qty in bundle['items'].items():
            if item not in ITEMS or not isinstance(qty, int) or qty < 1 or owner['items'].get(item, 0) < qty:
                raise ValueError('The offered items are unavailable.')
    for source, target, bundle in ((a,b,offer), (b,a,request)):
        for pid in bundle['pokemon']:
            target['box'][pid] = remove_pokemon(source, pid)
        for item, qty in bundle['items'].items():
            source['items'][item] -= qty
            target['items'][item] = target['items'].get(item, 0) + qty


# Custom bot rewards: a small supply spin, not premium balls or raid-only items.
POKESTOP_COOLDOWN = 300
POKESTOP_LOOT = {
    'poke-ball': 40, 'great-ball': 15, 'ultra-ball': 5,
    'potion': 12, 'super-potion': 8, 'hyper-potion': 4, 'max-potion': 1,
    'revive': 5, 'max-revive': 1, 'razz-berry': 5, 'pinap-berry': 4,
}


def spin_pokestop(player, now, rng=random):
    """Apply rewards and cooldown together; caller commits under the guild lock."""
    remaining = player.get('last_pokestop', 0) + POKESTOP_COOLDOWN - now
    if remaining > 0:
        raise ValueError(f'Your Pokéstop is recharging. Try again in {math.ceil(remaining)} seconds.')
    items = {}
    for item in rng.choices(list(POKESTOP_LOOT), weights=list(POKESTOP_LOOT.values()), k=rng.randint(3, 6)):
        items[item] = items.get(item, 0) + 1
    dust = rng.randint(50, 150)
    for item, quantity in items.items():
        player['items'][item] = player['items'].get(item, 0) + quantity
    player['dust'] += dust
    player['last_pokestop'] = now
    return items, dust
