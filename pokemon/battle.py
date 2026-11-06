"""Friendly turn-based battles. Deliberately limited to direct-damage moves.

Data for all moves is retained in the Dex. Unsupported effects are not silently
approximated: battle menus offer only moves supported by this first engine.
"""
import asyncio
import copy
import random

import discord
from .rules import account, stats, hidden_power
from .pokemon import View, embed, reply

# Effect 1 is ordinary damage. Other effects require their own implementations.
SUPPORTED_EFFECTS = {1, 136}  # Ordinary damage and Hidden Power.


def supported(move):
    return move['power'] > 0 and move['class'] in (2,3) and move['effect'] in SUPPORTED_EFFECTS


def damage(attacker, defender, move, dex, rng=random):
    a, d = stats(attacker, dex), stats(defender, dex)
    kind = hidden_power(attacker['ivs']) if move['name'] == 'hidden-power' else move['type']
    physical = move['class'] == 2
    offense, defense = (a[1],d[2]) if physical else (a[3],d[4])
    value = ((2*attacker['level']//5+2)*max(1,move['power'])*offense/max(1,defense)/50)+2
    if move['name'] != 'struggle':
        if kind in dex.pokemon[attacker['pokemon_id']]['types']: value *= 1.5
        for target_type in dex.pokemon[defender['pokemon_id']]['types']:
            value *= dex.efficacy.get((kind,target_type),1)
    if value == 0: return 0
    return max(1, int(value*rng.uniform(.85,1)))


class Challenge(View):
    def __init__(self, cog, owner, challenger):
        super().__init__(cog, owner, timeout=120)
        self.challenger, self.used = challenger, False
        button = discord.ui.Button(label='Accept friendly battle', style=discord.ButtonStyle.success)
        button.callback = self.accept
        self.add_item(button)

    async def accept(self, i):
        if self.used: return await reply(i, 'Already accepted', 'This challenge has been used.')
        self.used = True
        await i.response.defer(ephemeral=True)
        try:
            async with self.cog.lock(i.guild_id):
                state = await self.cog.available(i.guild_id)
                teams = {}
                for uid in (self.challenger, self.owner):
                    self.cog.ensure_unlocked(state, uid)
                    p = account(state, uid)
                    if len(p['party']) != 6 or any(pid not in p['box'] for pid in p['party']):
                        raise ValueError('Both trainers need a party of exactly six Pokémon.')
                    team = [copy.deepcopy(p['box'][pid]) for pid in p['party']]
                    if not any(mon['hp'] > 0 for mon in team): raise ValueError('Both teams need at least one non-fainted Pokémon. Use healing items.')
                    teams[uid] = team
                game = Battle(self.cog, i.guild_id, teams)
                for uid in teams: self.cog.active_battles[(i.guild_id,uid)] = game
            try:
                game.message = await i.channel.send(embed=game.render(), view=game,
                    allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                game.release()
                raise
            await reply(i, 'Battle started', 'Choose your move using the public battle buttons.')
        except ValueError as error:
            await reply(i, 'Cannot start battle', str(error))


async def challenge(cog, i, member_id):
    target = i.guild.get_member(int(member_id))
    if not target or target.bot or target.id == i.user.id: raise ValueError('Choose another human member.')
    await cog.available(i.guild_id)
    await i.channel.send(embed=embed('Friendly battle challenge',
        f'<@{i.user.id}> challenges <@{target.id}>! Both trainers need six party Pokémon.\n'
        'This first battle engine supports ordinary direct-damage moves, types, stats, IVs, EVs, natures, Hidden Power, PP, switching, and fainting. '
        'Abilities, held items, status moves, and special move effects are not yet supported. Unsupported moves are excluded from move selection. No currency is wagered.'),
        view=Challenge(cog, target.id, i.user.id), allowed_mentions=discord.AllowedMentions.none())
    await reply(i, 'Challenge sent', 'Your opponent has two minutes to accept.')


class Battle(View):
    def __init__(self, cog, gid, teams):
        super().__init__(cog, timeout=300)
        self.gid, self.teams, self.players = gid, teams, list(teams)
        self.active = {uid: next(j for j,p in enumerate(team) if p['hp'] > 0) for uid,team in teams.items()}
        self.pp = {p['id']: {m:cog.dex.moves[m]['pp'] for m in p['moves']} for team in teams.values() for p in team}
        self.choices, self.lines, self.turn, self.done = {}, [], 1, False
        self.guard, self.message = asyncio.Lock(), None
        for label, action in [('Choose move','move'), ('Switch Pokémon','switch'), ('Forfeit','forfeit')]:
            button = discord.ui.Button(label=label)
            async def click(i, action=action):
                if i.user.id not in self.teams: return await reply(i, 'Battle in progress', 'Only the two trainers can use these buttons.')
                if self.done: return await reply(i, 'Battle ended', 'This battle is over.')
                if action == 'forfeit':
                    await i.response.defer(ephemeral=True)
                    async with self.guard:
                        await self.finish(f'<@{i.user.id}> forfeited.', save=True)
                    return await reply(i, 'Battle ended', 'You forfeited the battle.')
                view = Choices(self, i.user.id, action)
                await reply(i, 'Select your action', 'Actions resolve together after both trainers choose. You can replace your choice until the turn resolves.', view)
            button.callback = click
            self.add_item(button)

    def release(self):
        self.done = True
        for uid in self.players:
            if self.cog.active_battles.get((self.gid,uid)) is self:
                self.cog.active_battles.pop((self.gid,uid), None)
        self.stop()
        self.cog.views.discard(self)

    async def on_timeout(self):
        async with self.guard:
            if not self.done: await self.finish('Battle timed out. No HP changes were saved.', save=False)

    def render(self):
        rows = []
        for uid in self.players:
            p = self.teams[uid][self.active[uid]]
            alive = sum(mon['hp'] > 0 for mon in self.teams[uid])
            rows.append(f'<@{uid}> · **{p["name"]}** · {p["hp"]}/{stats(p,self.cog.dex)[0]} HP · {alive}/6 remaining')
        return embed(f'Friendly battle · turn {self.turn}', '\n'.join(rows + [''] + self.lines[-8:]))

    async def submit(self, i, action, expected_turn):
        await i.response.defer(ephemeral=True)
        async with self.guard:
            if self.done: return await reply(i, 'Battle ended', 'This battle is over.')
            if self.turn != expected_turn:
                return await reply(i, 'Old turn', 'Open a fresh action menu.')
            try:
                await self.cog.available(self.gid)
            except ValueError:
                await self.finish('Pokémon was disabled. Battle cancelled.', save=False)
                return await reply(i, 'Battle cancelled', 'Pokémon is disabled in this server.')
            self.choices[i.user.id] = action
            if len(self.choices) < 2: return await reply(i, 'Action ready', 'Waiting for your opponent.')
            try:
                await self.resolve()
                await reply(i, 'Turn resolved', 'See the battle message for the result.')
            except Exception:
                await self.finish('Battle interrupted. No HP changes were saved.', save=False)
                raise

    async def resolve(self):
        dex = self.cog.dex
        choices = self.choices
        self.choices = {}
        order = list(self.players)
        random.shuffle(order)
        def priority(uid):
            action, value = choices[uid]
            p = self.teams[uid][self.active[uid]]
            return (6 if action == 'switch' else dex.moves[value]['priority'], stats(p,dex)[5])
        order.sort(key=priority, reverse=True)
        self.lines = []
        for uid in order:
            other = next(v for v in self.players if v != uid)
            p = self.teams[uid][self.active[uid]]
            target = self.teams[other][self.active[other]]
            action, value = choices[uid]
            if action == 'switch':
                if 0 <= value < 6 and self.teams[uid][value]['hp'] > 0:
                    self.active[uid] = value
                    self.lines.append(f'<@{uid}> switched to {self.teams[uid][value]["name"]}.')
                continue
            if p['hp'] <= 0: continue
            if target['hp'] <= 0: continue
            if value != 165:
                if value not in p['moves'] or not supported(dex.moves[value]) or self.pp[p['id']].get(value,0) <= 0: continue
                self.pp[p['id']][value] -= 1
            move = dex.moves[value]
            if random.random()*100 >= move['accuracy']:
                self.lines.append(f'{p["name"]} used {move["name"]} and missed.')
                continue
            hurt = damage(p,target,move,dex)
            target['hp'] = max(0,target['hp']-hurt)
            if target['hp'] == 0:
                # Award canonical species EV yields, respecting per-stat and total caps.
                for j, effort in enumerate(dex.pokemon[target['pokemon_id']]['effort']):
                    gain = min(effort, 252-p['evs'][j], 510-sum(p['evs']))
                    p['evs'][j] += max(0,gain)
            self.lines.append(f'{p["name"]} used {move["name"]}: {hurt} damage.')
            if value == 165:
                p['hp'] = max(0,p['hp']-max(1,stats(p,dex)[0]//4))
                self.lines.append(f'{p["name"]} took Struggle recoil.')
        for uid in self.players:
            living = [j for j,p in enumerate(self.teams[uid]) if p['hp'] > 0]
            if living and self.teams[uid][self.active[uid]]['hp'] <= 0:
                self.active[uid] = living[0]
                self.lines.append(f'<@{uid}> sent out {self.teams[uid][living[0]]["name"]}.')
        surviving = [uid for uid in self.players if any(p['hp'] > 0 for p in self.teams[uid])]
        if len(surviving) < 2:
            return await self.finish(f'<@{surviving[0]}> wins!' if surviving else 'The battle is a draw.', save=True)
        self.turn += 1
        if self.turn > 200: return await self.finish('Turn limit reached: draw.', save=True)
        await self.message.edit(embed=self.render(), view=self)

    async def finish(self, text, save):
        if self.done: return
        if save:
            async with self.cog.lock(self.gid):
                state = await self.cog.state(self.gid)
                # Only HP and earned EVs are persisted; no snapshot overwrites purchases or captures.
                for uid, team in self.teams.items():
                    player = state['players'].get(str(uid))
                    if not player: continue
                    for p in team:
                        if p['id'] in player['box']:
                            player['box'][p['id']]['hp'] = p['hp']
                            player['box'][p['id']]['evs'] = p['evs']
                await self.cog.save(self.gid, state)
        self.lines.append(text)
        self.release()
        if self.message: await self.message.edit(embed=self.render(), view=None)


class Choices(View):
    def __init__(self, game, owner, action):
        super().__init__(game.cog, owner, timeout=90)
        self.game = game
        self.turn = game.turn
        p = game.teams[owner][game.active[owner]]
        if action == 'move':
            moves = [m for m in p['moves'] if supported(game.cog.dex.moves[m]) and game.pp[p['id']].get(m,0) > 0]
            moves = moves or [165]
            options = [discord.SelectOption(label=f'{game.cog.dex.moves[m]["name"]} · PP {game.pp[p["id"]].get(m,"∞")}', value=str(m)) for m in moves]
        else:
            options = [discord.SelectOption(label=f'{j+1}: {mon["name"]} ({mon["hp"]} HP)', value=str(j))
                       for j,mon in enumerate(game.teams[owner]) if mon['hp'] > 0 and j != game.active[owner]]
        if not options:
            self.add_item(discord.ui.Button(label='No available switch', disabled=True))
            return
        select = discord.ui.Select(placeholder='Choose an action', options=options)
        async def choose(i):
            if game.turn != self.turn: return await reply(i, 'Old turn', 'Open a fresh action menu.')
            await game.submit(i, (action,int(select.values[0])), self.turn)
        select.callback = choose
        self.add_item(select)
