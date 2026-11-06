"""Global trainer storage with an atomic, repeat-safe legacy migration."""
import asyncio
import copy
import uuid

from .rules import account

SHARED = ('players', 'orders', 'trades')


def migrate(legacy):
    world = {'schema': 1, 'players': {}, 'orders': {}, 'trades': {}, 'guilds': {}, 'interval': 1800}
    intervals = {int(s.get('interval', 1800)) for s in legacy.values()}
    if len(intervals) == 1:
        world['interval'] = max(300, min(86400, intervals.pop()))
    used_ids = set()
    for gid, original in sorted(legacy.items()):
        state = copy.deepcopy(original)
        local = {k:v for k,v in state.items() if k not in SHARED and k != 'interval'}
        spawn = local.get('spawn')
        if spawn and 'spawned_at' not in spawn:
            spawn['spawned_at'] = state.get('next_spawn', 0) - int(state.get('interval', 1800))
        world['guilds'][str(gid)] = local
        remaps = {}
        for uid in state.get('players', {}):
            source = account(state, uid)
            first = uid not in world['players']
            if first:
                target = copy.deepcopy(source)
                target['box'], target['party'] = {}, []
                world['players'][uid] = target
            else:
                target = world['players'][uid]
                for key in ('xp','dust'): target[key] += source.get(key, 0)
                for key in ('items','candy'):
                    for name, amount in source.get(key, {}).items():
                        target[key][name] = target[key].get(name, 0) + amount
                target['last_pokestop'] = max(target.get('last_pokestop', 0), source.get('last_pokestop', 0))
                target['receipts'] = list(dict.fromkeys(target.get('receipts', []) + source.get('receipts', [])))
                for sid, entry in source['pokedex'].items():
                    if sid not in target['pokedex']: target['pokedex'][sid] = copy.deepcopy(entry)
                    else:
                        target['pokedex'][sid]['caught'] += entry['caught']
                        target['pokedex'][sid]['shiny'] |= entry['shiny']
            remap = {}
            for pid, pokemon in source['box'].items():
                new_id = pid
                if pid in used_ids:
                    new_id = uuid.uuid4().hex[:12]
                    while new_id in used_ids: new_id = uuid.uuid4().hex[:12]
                used_ids.add(new_id)
                mon = copy.deepcopy(pokemon)
                mon['id'] = new_id
                target['box'][new_id] = mon
                remap[pid] = new_id
            remaps[uid] = remap
            if not target['party']:
                target['party'] = [remap[pid] for pid in source.get('party', []) if pid in remap][:6]
        for oid, order in state.get('orders', {}).items():
            key = oid if oid not in world['orders'] else f'{gid}:{oid}'
            record = copy.deepcopy(order)
            record['guild_id'] = gid
            record['original_id'] = oid
            if record.get('kind') == 'trade':
                trade = record['trade']
                for side, user_key in (('offer','from'),('request','to')):
                    mapping = remaps.get(str(trade[user_key]), {})
                    trade[side]['pokemon'] = [mapping.get(pid, pid) for pid in trade[side]['pokemon']]
            world['orders'][key] = record
    # Pending proposals are deliberately expired on migration, before any payment.
    return world


class GlobalStore:
    def __init__(self, config):
        self.config = config
        self.migration_lock = asyncio.Lock()

    async def world(self):
        async with self.migration_lock:
            world = await self.config.world(default={})
            if world.get('schema') == 1: return world
            legacy = {}
            for gid in await self.config.all_guilds():
                legacy[gid] = await self.config.guild_from_id(gid).state(default={})
            world = migrate(legacy)
            # Marker and imported assets commit together: restarts cannot re-import.
            await self.config.world.set(world)
            return world

    async def read(self, gid):
        world = await self.world()
        state = copy.deepcopy(world['guilds'].get(str(gid), {}))
        for key in SHARED: state[key] = copy.deepcopy(world[key])
        state['interval'] = world['interval']
        return state

    async def save(self, gid, state):
        world = await self.world()
        interval_changed = world['interval'] != state['interval']
        for key in SHARED: world[key] = copy.deepcopy(state[key])
        world['guilds'][str(gid)] = {k:copy.deepcopy(v) for k,v in state.items() if k not in SHARED and k != 'interval'}
        world['interval'] = state['interval']
        if interval_changed:
            # All servers start their new owner-selected cadence from this update.
            import time
            for guild in world['guilds'].values():
                guild['next_spawn'] = time.time() + world['interval']
        await self.config.world.set(world)

    async def guild_ids(self):
        return set(int(gid) for gid in (await self.world())['guilds'])

    async def delete_user(self, uid):
        world = await self.world()
        self.scrub(world, uid)
        for guild in world['guilds'].values(): self.scrub(guild, uid)
        await self.config.world.set(world)
        # Legacy copies are retained as recovery backups, never imported twice.
        for gid in await self.config.all_guilds():
            legacy = await self.config.guild_from_id(gid).state(default={})
            self.scrub(legacy, uid)
            await self.config.guild_from_id(gid).state.set(legacy)

    @staticmethod
    def scrub(state, uid):
        state.get('players', {}).pop(str(uid), None)
        if 'orders' in state:
            state['orders'] = {key:o for key,o in state['orders'].items() if o.get('user') != uid and uid not in o.get('users', [])}
        if 'trades' in state:
            state['trades'] = {key:t for key,t in state['trades'].items() if uid not in (t['from'],t['to'])}
        if state.get('spawn'): state['spawn'].get('attempts', {}).pop(str(uid), None)
        for record in state.get('pending_spawn_edits', {}).values():
            record.get('spawn', {}).get('attempts', {}).pop(str(uid), None)
