"""Opt-in Pokémon collections for Red. All player input is component based."""
import asyncio
import copy
import math
import logging
import random
import time
import uuid

import discord
from discord.ext import tasks
from redbot.core import Config, bank, commands
from redbot.core.data_manager import cog_data_path

from .dex import Dex
from .rules import (ITEMS, BALLS, account, bonus, choose_species, new_pokemon,
                    catch_chance, stats, hidden_power, remove_pokemon, transfer, swap, spin_pokestop)

log = logging.getLogger('red.pokemon')
ENCOUNTER_SECONDS = 300


def embed(title, text):
    return discord.Embed(title=title, description=str(text)[:4000], color=0xEF5350)


async def reply(i, title, text, view=None):
    kwargs = dict(embed=embed(title, text), ephemeral=True, view=view,
                  allowed_mentions=discord.AllowedMentions.none())
    if i.response.is_done(): await i.followup.send(**kwargs)
    else: await i.response.send_message(**kwargs)


class View(discord.ui.View):
    def __init__(self, cog, owner=None, timeout=180):
        super().__init__(timeout=timeout)
        self.cog, self.owner = cog, owner
        cog.views.add(self)

    async def interaction_check(self, i):
        if self.cog.bot.get_cog('Pokemon') is not self.cog:
            await reply(i, 'Reloaded', 'Open the Pokémon menu again.')
            return False
        if self.owner is not None and i.user.id != self.owner:
            await reply(i, 'Private menu', 'Open your own Pokémon menu.')
            return False
        return True

    async def on_timeout(self):
        self.cog.views.discard(self)

    async def on_error(self, i, error, item):
        log.error('Pokémon interaction failed', exc_info=(type(error), error, error.__traceback__))
        await reply(i, 'Unable to complete', 'The request failed. Check your collection or order status before retrying.')


class Input(discord.ui.Modal):
    def __init__(self, cog, action, fields, callback):
        super().__init__(title=action[:45])
        self.cog, self.callback_fn = cog, callback
        for label, placeholder in fields:
            self.add_item(discord.ui.TextInput(label=label[:45], placeholder=placeholder[:100], max_length=500))

    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        if self.cog.bot.get_cog('Pokemon') is not self.cog:
            return await reply(i, 'Reloaded', 'Open the menu again.')
        try:
            await self.callback_fn(i, *[str(c.value).strip() for c in self.children])
        except (ValueError, KeyError) as error:
            await reply(i, 'Check your selection', str(error))
        except Exception:
            log.exception('Pokémon modal failed')
            await reply(i, 'Unable to complete', 'Request failed. Check your collection and orders before trying again.')


class Confirm(View):
    def __init__(self, cog, owner, callback, label='Confirm'):
        super().__init__(cog, owner)
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.danger)
        button.callback = self.confirm
        self.add_item(button)
        self.action, self.used = callback, False

    async def confirm(self, i):
        if self.used:
            return await reply(i, 'Already submitted', 'This confirmation has already been used.')
        self.used = True
        await i.response.defer(ephemeral=True)
        try:
            await self.action(i)
        except ValueError as error:
            await reply(i, 'Unable to complete', str(error))
        finally:
            self.stop()
            self.cog.views.discard(self)


class Spawn(View):
    def __init__(self, cog):
        super().__init__(cog, timeout=None)
        button = discord.ui.Button(label='Catch Pokémon', style=discord.ButtonStyle.success,
                                   custom_id='pokemon:catch:v1')
        button.callback = self.open
        self.add_item(button)

    async def open(self, i):
        state = await self.cog.state(i.guild_id)
        spawn = state.get('spawn')
        if not state['enabled'] or not spawn or spawn.get('message') != i.message.id or spawn['expires'] <= time.time():
            return await reply(i, 'Gone', 'This Pokémon is no longer available.')
        await reply(i, 'Choose a ball', 'A ball is consumed per attempt. Everyone shares this encounter.',
                    Catch(self.cog, i.user.id, spawn['id']))


class Catch(View):
    def __init__(self, cog, owner, spawn_id):
        super().__init__(cog, owner)
        self.spawn_id, self.ball, self.berry = spawn_id, 'poke-ball', None
        names = list(BALLS)
        for start in range(0, len(names), 25):
            select = discord.ui.Select(placeholder='Choose a ball' if start == 0 else 'More ball types', options=[discord.SelectOption(label=k, value=k) for k in names[start:start+25]])
            async def choose(i, select=select):
                self.ball = select.values[0]
                await i.response.defer()
            select.callback = choose
            self.add_item(select)
        berries = discord.ui.Select(placeholder='Optional berry', options=[
            discord.SelectOption(label='No berry', value='none'),
            discord.SelectOption(label='Razz Berry: catch bonus', value='razz-berry'),
            discord.SelectOption(label='Pinap Berry: double candy', value='pinap-berry')])
        async def berry(i):
            self.berry = None if berries.values[0] == 'none' else berries.values[0]
            await i.response.defer()
        berries.callback = berry
        self.add_item(berries)
        button = discord.ui.Button(label='Throw ball', style=discord.ButtonStyle.success)
        button.callback = self.throw
        self.add_item(button)

    async def throw(self, i):
        await i.response.defer(ephemeral=True)
        try:
            message = await self.cog.catch(i, self.spawn_id, self.ball, self.berry)
            await reply(i, 'Catch result', message)
        except ValueError as error:
            await reply(i, 'Cannot throw', str(error))


class ChannelChoice(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder='Select the spawn channel', channel_types=[discord.ChannelType.text])

    async def callback(self, i):
        if not await self.view.cog.admin(i): return
        channel = i.guild.get_channel(self.values[0].id)
        perms = channel.permissions_for(i.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            return await reply(i, 'Missing permissions', 'I need View Channel, Send Messages, and Embed Links there.')
        async with self.view.cog.lock(i.guild_id):
            state = await self.view.cog.state(i.guild_id)
            state['channel'] = channel.id
            state['spawn'] = None
            state['next_spawn'] = time.time() + state['interval']
            await self.view.cog.save(i.guild_id, state)
        await reply(i, 'Channel saved', f'Wild Pokémon will appear in <#{channel.id}> when enabled.')


class Menu(View):
    def __init__(self, cog, owner, admin=False):
        super().__init__(cog, owner)
        self.admin_menu = admin
        if admin:
            actions = ['Settings', 'Enable / disable', 'Spawn channel', 'Interval',
                       'Notification role', 'Role bonuses', 'Give Pokémon', 'Take Pokémon',
                       'Give / take items', 'Force evolve', 'Wipe box', 'Orders']
            for index, action in enumerate(actions):
                button = discord.ui.Button(label=action, row=index // 4,
                    style=discord.ButtonStyle.danger if action == 'Wipe box' else discord.ButtonStyle.secondary)
                async def choose(i, action=action):
                    if not await cog.admin(i): return
                    try:
                        await cog.route(i, action, admin=True)
                    except ValueError as error:
                        await reply(i, 'Unable to complete', str(error))
                button.callback = choose
                self.add_item(button)
            return
        actions = ['Trainer', 'PC box', 'Inspect', 'Party', 'Transfer', 'Power up', 'Evolve', 'Shop',
                   'Inventory', 'Trade', 'Battle', 'Pokéstop', 'Catch', 'Orders']
        select = discord.ui.Select(placeholder='Choose an action', options=[discord.SelectOption(label=a) for a in actions])
        async def choose(i):
            try:
                await cog.route(i, select.values[0])
            except ValueError as error:
                await reply(i, 'Unable to complete', str(error))
        select.callback = choose
        self.add_item(select)


class Box(View):
    def __init__(self, cog, owner, pokemon):
        super().__init__(cog, owner)
        self.pokemon, self.page = pokemon, 0
        for name, delta in [('Previous', -1), ('Next', 1)]:
            button = discord.ui.Button(label=name)
            async def move(i, delta=delta):
                self.page = max(0, min((len(self.pokemon)-1)//15, self.page + delta))
                await i.response.edit_message(embed=self.render())
            button.callback = move
            self.add_item(button)

    def render(self):
        lines = [f"`{p['id']}` {'✨ ' if p['shiny'] else ''}{p['name']} · Lv {p['level']}" for p in self.pokemon[self.page*15:self.page*15+15]]
        return embed(f'PC box · page {self.page+1}', '\n'.join(lines) or 'Your box is empty. Catch a wild Pokémon to begin.')


class Trade(View):
    def __init__(self, cog, target, trade_id):
        super().__init__(cog, target, timeout=300)
        self.trade_id = trade_id
        for label, accept in [('Accept trade', True), ('Decline trade', False)]:
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.success if accept else discord.ButtonStyle.secondary)
            async def respond(i, accept=accept):
                await i.response.defer(ephemeral=True)
                try:
                    await cog.finish_trade(i, trade_id, accept)
                except ValueError as error:
                    await reply(i, 'Trade unavailable', str(error))
            button.callback = respond
            self.add_item(button)


class Pokemon(commands.Cog):
    """An opt-in Pokémon collection game. Raids are reserved for a later release."""
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=981376420021, force_registration=True)
        self.config.register_guild(state={'enabled': False, 'channel': None, 'interval': 1800,
            'next_spawn': 0, 'spawn': None, 'notify_role': None, 'roles': {}, 'players': {}, 'trades': {}, 'orders': {}})
        self.dex = Dex(cog_data_path(self) / 'dex')
        self.locks, self.bank_locks, self.views = {}, {}, set()
        self.active_battles = {}
        self.expiry_tasks = {}

    async def cog_load(self):
        self.spawn_view = Spawn(self)
        self.bot.add_view(self.spawn_view)
        self.scheduler.start()

    def cog_unload(self):
        self.scheduler.cancel()
        for task in self.expiry_tasks.values():
            task.cancel()
        self.expiry_tasks.clear()
        for view in list(self.views):
            view.stop()
        self.views.clear()

    def lock(self, gid):
        return self.locks.setdefault(gid, asyncio.Lock())

    def bank_lock(self, uid):
        return self.bank_locks.setdefault(uid, asyncio.Lock())

    async def state(self, gid):
        state = await self.config.guild_from_id(gid).state()
        state.setdefault('notify_role', None)
        # Bound old encounters, whose expiry was tied to the spawn interval.
        spawn = state.get('spawn')
        if spawn:
            started = spawn.get('spawned_at', state['next_spawn'] - state['interval'])
            spawn['expires'] = min(spawn['expires'], started + ENCOUNTER_SECONDS)
        return state

    async def save(self, gid, state):
        await self.config.guild_from_id(gid).state.set(state)

    async def admin(self, i):
        if self.bot.get_cog('Pokemon') is not self:
            await reply(i, 'Reloaded', 'Open the settings again.')
            return False
        if await self.bot.is_owner(i.user) or i.user.guild_permissions.administrator or await self.bot.is_admin(i.user): return True
        await reply(i, 'Administrator only', 'You need server administrator permissions or a configured bot admin role.')
        return False

    async def available(self, gid, *, load_dex=True):
        state = await self.state(gid)
        guild = self.bot.get_guild(gid)
        if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
            raise ValueError('The Pokémon cog is disabled in this server.')
        if not state['enabled']: raise ValueError('Pokémon is disabled here. Ask an administrator to use pokeset.')
        if load_dex and not self.dex.species: await self.dex.load()
        return state

    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    @commands.command(name='pokemon', aliases=['poke'])
    async def pokemon(self, ctx):
        """Open your Pokémon menu."""
        state = await self.state(ctx.guild.id)
        if not state['enabled']:
            return await ctx.send(embed=embed('Pokémon disabled', 'An administrator can configure and enable this game with pokeset.'))
        await ctx.send(embed=embed('Pokémon', 'Catch wild Pokémon, manage your party, shop, and trade. Use the menu below.'),
                       view=Menu(self, ctx.author.id))

    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    @commands.command(name='pokestop')
    async def pokestop(self, ctx):
        """Spin your Pokéstop for random supplies and Stardust every five minutes."""
        try:
            items, dust = await self.spin_stop(ctx.guild.id, ctx.author.id)
        except ValueError as error:
            return await ctx.send(embed=embed('Pokéstop', str(error)))
        await ctx.send(embed=embed('Pokéstop rewards', self.stop_rewards(items, dust)))

    async def spin_stop(self, gid, uid):
        async with self.lock(gid):
            state = await self.available(gid, load_dex=False)
            self.ensure_unlocked(state, uid)
            rewards = spin_pokestop(account(state, uid), time.time())
            await self.save(gid, state)
            return rewards

    @staticmethod
    def stop_rewards(items, dust):
        return '\n'.join(f'+{quantity} × {item}' for item, quantity in items.items()) + f'\n+{dust} Stardust\nSpin again in five minutes.'

    async def current_encounter(self, gid, channel_id):
        state = await self.available(gid, load_dex=False)
        spawn = state['spawn']
        if channel_id != state['channel']:
            raise ValueError(f"Use the catch command in <#{state['channel']}>.")
        if not spawn or spawn['expires'] <= time.time() or not spawn.get('message'):
            raise ValueError('There is no wild Pokémon to catch right now.')
        return spawn

    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    @commands.command(name='pokecatch', aliases=['catch'])
    async def pokecatch(self, ctx):
        """Choose a ball to catch the current wild Pokémon in the spawn channel."""
        try:
            spawn = await self.current_encounter(ctx.guild.id, ctx.channel.id)
        except ValueError as error:
            return await ctx.send(embed=embed('Cannot catch', str(error)))
        await ctx.send(embed=embed('Choose a ball', 'A ball is consumed per attempt. The first successful trainer keeps this Pokémon.'),
                       view=Catch(self, ctx.author.id, spawn['id']))

    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    @commands.bot_has_permissions(embed_links=True)
    @commands.command(name='pokeset')
    async def pokeset(self, ctx):
        """Open Pokémon server settings and moderation tools."""
        await ctx.send(embed=embed('Pokémon settings', 'Use the buttons to configure this server. Choose Spawn channel, then explicitly enable spawning. Default interval: 30 minutes.'),
                       view=Menu(self, ctx.author.id, admin=True))

    @tasks.loop(seconds=30)
    async def scheduler(self):
        for gid in await self.config.all_guilds():
            try:
                state = await self.state(gid)
                if not self.bot.get_guild(gid): continue
                if state['spawn']:
                    self.schedule_expiry(gid, state['spawn'])
                    await self.expire_spawn(gid, state['spawn']['id'])
                if not state['enabled'] or not state['channel'] or state['next_spawn'] > time.time(): continue
                if await self.bot.cog_disabled_in_guild(self, self.bot.get_guild(gid)): continue
                await self.dex.load()
                await self.spawn(gid)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Pokémon spawn failed for guild %s', gid)

    @scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_red_ready()
        for gid in await self.config.all_guilds():
            state = await self.state(gid)
            if state['spawn']: self.schedule_expiry(gid, state['spawn'])

    def schedule_expiry(self, gid, spawn):
        existing = self.expiry_tasks.get(gid)
        if existing and not existing.done(): return
        async def wait_for_flee():
            try:
                while spawn['expires'] > time.time():
                    await asyncio.sleep(max(0, spawn['expires'] - time.time()))
                await self.expire_spawn(gid, spawn['id'])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Pokémon expiry failed for guild %s', gid)
            finally:
                if self.expiry_tasks.get(gid) is asyncio.current_task():
                    self.expiry_tasks.pop(gid, None)
        self.expiry_tasks[gid] = asyncio.create_task(wait_for_flee())

    async def edit_encounter(self, gid, spawn, title, text):
        guild = self.bot.get_guild(gid)
        channel_id = spawn.get('channel') or (await self.state(gid))['channel']
        channel = guild and guild.get_channel(channel_id)
        if not channel or not spawn.get('message'): return
        try:
            await channel.get_partial_message(spawn['message']).edit(
                embed=embed(title, text), view=None, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.warning('Unable to update Pokémon encounter %s in guild %s', spawn['id'], gid)

    async def expire_spawn(self, gid, spawn_id):
        async with self.lock(gid):
            state = await self.state(gid)
            spawn = state['spawn']
            if not spawn or spawn['id'] != spawn_id or spawn['expires'] > time.time(): return False
            state['spawn'] = None
            await self.save(gid, state)
        await self.edit_encounter(gid, spawn, 'The wild Pokémon fled!',
                                  f"{spawn['pokemon']['name'].replace('-', ' ').title()} escaped after five minutes.")
        return True

    async def spawn(self, gid):
        async with self.lock(gid):
            state = await self.state(gid)
            guild = self.bot.get_guild(gid)
            channel = guild and guild.get_channel(state['channel'])
            if not state['enabled'] or not channel or state['next_spawn'] > time.time(): return
            if state['spawn'] and state['spawn']['expires'] > time.time(): return
            # One public species is selected. Registered role holders influence its rarity for everyone.
            rare = max((bonus(state, [r.id for r in m.roles])['rare'] for m in guild.members
                        if not m.bot and str(m.id) in state['players']), default=1)
            species = choose_species(self.dex.species, rare)
            pokemon = new_pokemon(species, self.dex)
            # Shiny is rolled for the successful catcher, not for each throw.
            pokemon['shiny'] = False
            now = time.time()
            state['spawn'] = {'id': uuid.uuid4().hex, 'pokemon': pokemon, 'message': None,
                              'spawned_at': now, 'channel': channel.id,
                              'expires': now + ENCOUNTER_SECONDS, 'attempts': {}}
            state['next_spawn'] = now + state['interval']
            # Persist before posting: a crash cannot create two catchable encounters.
            await self.save(gid, state)
            role = guild.get_role(state['notify_role']) if state['notify_role'] else None
            can_ping = role and not role.is_default() and not role.managed and (
                role.mentionable or channel.permissions_for(guild.me).mention_everyone)
            message = await channel.send(content=f'<@&{role.id}>' if can_ping else None,
                embed=embed('A wild Pokémon appeared!',
                f"**{species['name'].replace('-', ' ').title()}** · Level {pokemon['level']}\nUse the Catch button or the pokecatch command to throw a ball. Fleeing <t:{int(now + ENCOUNTER_SECONDS)}:R> (five minutes)."),
                view=self.spawn_view,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=False,
                                                        roles=[role] if can_ping else [], replied_user=False))
            state['spawn']['message'] = message.id
            await self.save(gid, state)
            previous = self.expiry_tasks.pop(gid, None)
            if previous: previous.cancel()
            self.schedule_expiry(gid, state['spawn'])

    async def catch(self, i, spawn_id, ball, berry):
        async with self.lock(i.guild_id):
            state = await self.available(i.guild_id)
            spawn = state['spawn']
            if not spawn or spawn['id'] != spawn_id or spawn['expires'] <= time.time():
                raise ValueError('This Pokémon has already been caught or has left.')
            player = account(state, i.user.id)
            if player['items'].get(ball, 0) < 1: raise ValueError('You do not have that ball. Visit the shop.')
            if berry and player['items'].get(berry, 0) < 1: raise ValueError('You do not have that berry.')
            uid = str(i.user.id)
            attempts = spawn['attempts'].get(uid, {'count': 0, 'last': 0})
            if time.time() - attempts['last'] < 5: raise ValueError('Wait five seconds between throws.')
            player['items'][ball] -= 1
            if berry: player['items'][berry] -= 1
            perks = bonus(state, [r.id for r in i.user.roles])
            pokemon = spawn['pokemon']
            species = self.dex.species[pokemon['species']]
            chance = catch_chance(ball, pokemon, species, player, perks, attempts['count'], berry)
            spawn['attempts'][uid] = {'count': attempts['count']+1, 'last': time.time()}
            if random.random() >= chance:
                await self.save(i.guild_id, state)
                return 'The Pokémon broke free! Your ball was used. You can try again in five seconds.'
            pokemon['shiny'] = random.random() < min(1, perks['shiny']/4096)
            player['box'][pokemon['id']] = pokemon
            xp, candy = int(100*perks['xp']), (3+int(perks['candy']))*(2 if berry == 'pinap-berry' else 1)
            player['xp'] += xp
            player['dust'] += 100
            family = str(species['family'])
            player['candy'][family] = player['candy'].get(family, 0) + candy
            state['spawn'] = None
            await self.save(i.guild_id, state)
            result = f"Caught {'✨ ' if pokemon['shiny'] else ''}**{pokemon['name']}**!\nID: `{pokemon['id']}` · +{xp} XP · +100 Stardust · +{candy} family Candy"
            expiry = self.expiry_tasks.pop(i.guild_id, None)
            if expiry: expiry.cancel()
        await self.edit_encounter(i.guild_id, spawn, 'Pokémon caught!',
                                  f"{pokemon['name'].replace('-', ' ').title()} was caught by <@{i.user.id}>.")
        return result

    def ensure_unlocked(self, state, uid):
        if any(key[1] == uid for key in self.active_battles):
            raise ValueError('Finish your active battle before changing your collection.')
        if any(o.get('kind') == 'trade' and o['status'] not in {'complete','cancelled','failed'} and uid in o['users'] for o in state['orders'].values()):
            raise ValueError('A currency trade needs owner review. Collection changes are locked to protect the exchange.')

    async def route(self, i, action, admin=False):
        if admin:
            return await self.admin_route(i, action)
        if action == 'Pokéstop':
            await i.response.defer(ephemeral=True)
            items, dust = await self.spin_stop(i.guild_id, i.user.id)
            return await reply(i, 'Pokéstop rewards', self.stop_rewards(items, dust))
        if action == 'Catch':
            spawn = await self.current_encounter(i.guild_id, i.channel_id)
            return await reply(i, 'Choose a ball', 'Throw a ball before this Pokémon flees.',
                               Catch(self, i.user.id, spawn['id']))
        if action in {'Trainer','PC box','Inventory','Orders','Shop'}:
            await i.response.defer(ephemeral=True)
            state = await self.available(i.guild_id)
            player = account(state, i.user.id)
            if action == 'Trainer':
                return await reply(i, 'Trainer', f"XP: {player['xp']:,}\nTrainer level: {min(50, 1 + int((player['xp']/1000)**.5))}\nStardust: {player['dust']:,}\nPokémon: {len(player['box'])}\nParty: {', '.join(player['party']) or 'Empty'}\nFamily Candy: {player['candy']}")
            if action == 'PC box':
                view = Box(self, i.user.id, list(player['box'].values()))
                return await i.followup.send(embed=view.render(), view=view, ephemeral=True)
            if action == 'Inventory': return await reply(i, 'Inventory', '\n'.join(f'{k}: {v}' for k,v in player['items'].items()) or 'Empty')
            if action == 'Orders': return await self.orders(i, state)
            if action == 'Shop':
                return await reply(i, 'Pokéshop', '\n'.join(f'{k}: {v:,}' for k,v in ITEMS.items()) + '\nPrices use the shared bot bank. Specialty balls without a listed bonus use their base catch rate.', Shop(self, i.user.id))
        fields = {
            'Inspect': [('Pokémon ID', 'Copy the ID from your PC box')],
            'Party': [('Pokémon IDs', 'Comma-separated IDs; one to six, in battle order')],
            'Transfer': [('Pokémon ID', 'Send one Pokémon to the professor for 1 Candy')],
            'Power up': [('Pokémon ID', 'Costs level × 100 Stardust and 2 Candy')],
            'Evolve': [('Pokémon ID', 'Costs 50 family Candy'), ('Target species', 'Pokédex number or name of a direct evolution')],
            'Trade': [('Member ID', 'Recipient Discord member ID'), ('Your Pokémon IDs', 'Comma separated, or none'),
                      ('Their Pokémon IDs', 'Comma separated, or none'), ('Items', 'offer:item=quantity;request:item=quantity, or none'),
                      ('Currency', 'Signed amount: positive you pay them; negative they pay you; 0 for none')],
            'Battle': [('Member ID', 'Opponent Discord member ID')]
        }
        async def submit(interaction, *values):
            await self.player_action(interaction, action, *values)
        await i.response.send_modal(Input(self, action, fields[action], submit))

    async def orders(self, i, state):
        rows = [f"`{key}` · {o['status']} · {o.get('price', o.get('currency', 0)):,}" for key,o in state['orders'].items()
                if o.get('user') == i.user.id or i.user.id in o.get('users', [])]
        await reply(i, 'Recent orders', '\n'.join(rows[-25:]) or 'No orders. Uncertain orders require bot owner review; they never charge automatically again.')

    async def player_action(self, i, action, *values):
        if action == 'Trade': return await self.offer_trade(i, *values)
        if action == 'Battle':
            from .battle import challenge
            return await challenge(self, i, values[0])
        async with self.lock(i.guild_id):
            state = await self.available(i.guild_id)
            self.ensure_unlocked(state, i.user.id)
            player = account(state, i.user.id)
            if action == 'Party':
                ids = [x.strip() for x in values[0].split(',')]
                if not 1 <= len(ids) <= 6 or len(set(ids)) != len(ids) or any(x not in player['box'] for x in ids):
                    raise ValueError('Choose one to six different Pokémon IDs from your box.')
                player['party'] = ids
                await self.save(i.guild_id, state)
                return await reply(i, 'Party saved', ', '.join(ids))
            pid = values[0]
            if pid not in player['box']: raise ValueError('That Pokémon is not in your box.')
            p = player['box'][pid]
            species = self.dex.species[p['species']]
            if action == 'Inspect':
                data = self.dex.pokemon[p['pokemon_id']]
                return await reply(i, p['name'], f"ID: `{pid}` · Level {p['level']} · {'Shiny' if p['shiny'] else 'Normal'}\nTypes: {', '.join(data['types'])}\nNature: {p['nature']}\nIVs: {p['ivs']}\nEVs: {p['evs']}\nStats (HP/Atk/Def/SpA/SpD/Spe): {stats(p, self.dex)}\nHidden Power: {hidden_power(p['ivs'])}\nHeight: {p['height']} m · Weight: {p['weight']} kg\nMoves: {', '.join(self.dex.moves[m]['name'] for m in p['moves'])}\nCandy: {player['candy'].get(str(species['family']), 0)}")
            if action == 'Transfer':
                async def confirmed(interaction):
                    async with self.lock(i.guild_id):
                        current = await self.available(i.guild_id)
                        self.ensure_unlocked(current, i.user.id)
                        transfer(account(current, i.user.id), pid, species['family'])
                        await self.save(i.guild_id, current)
                    await reply(interaction, 'Transferred', 'The professor sent 1 family Candy.')
                return await reply(i, 'Transfer permanently?', f"Send {p['name']} (`{pid}`) to the professor?", Confirm(self, i.user.id, confirmed))
            family = str(species['family'])
            if action == 'Power up':
                cost = p['level']*100
                trainer_level = min(50, 1 + int((player['xp']/1000)**.5))
                ceiling = min(100, max(30, trainer_level*2))
                if p['level'] >= ceiling:
                    raise ValueError(f'Your trainer level allows power-ups up to Pokémon level {ceiling}. Earn more trainer XP first.')
                if player['dust'] < cost or player['candy'].get(family,0) < 2: raise ValueError(f'You need {cost} Stardust and 2 family Candy.')
                player['dust'] -= cost
                player['candy'][family] -= 2
                p['level'] += 1
                p['moves'] = self.dex.learned_moves(p['pokemon_id'], p['level'])[-4:]
                p['hp'] = stats(p, self.dex)[0]
            elif action == 'Evolve':
                target = self.dex.resolve(values[1])
                if target['parent'] != p['species']: raise ValueError('Choose a direct evolution of this Pokémon.')
                if player['candy'].get(family, 0) < 50: raise ValueError('You need 50 family Candy.')
                player['candy'][family] -= 50
                self.evolve(p, target)
                player['xp'] += 500
            await self.save(i.guild_id, state)
            await reply(i, 'Pokémon updated', f"{p['name']} · Level {p['level']}")

    def evolve(self, p, target):
        old = self.dex.species[p['species']]
        p['height'] = round(p['height']*target['height']/max(1,old['height']), 2)
        p['weight'] = round(p['weight']*target['weight']/max(1,old['weight']), 2)
        p.update(species=target['id'], pokemon_id=target['pokemon_id'], name=target['name'])
        p['moves'] = self.dex.learned_moves(p['pokemon_id'], p['level'])[-4:]
        p['hp'] = stats(p, self.dex)[0]

    async def set_notification_role(self, i, value):
        if not await self.admin(i): return
        role_id = int(value.strip().removeprefix('<@&').removesuffix('>'))
        role = i.guild.get_role(role_id) if role_id else None
        if role_id and role is None:
            raise ValueError('That role no longer exists. Enter a server role ID, or 0 to disable pings.')
        if role and (role.is_default() or role.managed):
            raise ValueError('Choose a normal server role that members can opt into.')
        channel_id = (await self.state(i.guild_id))['channel']
        channel = i.guild.get_channel(channel_id) if channel_id else None
        permissions = channel.permissions_for(i.guild.me) if channel else i.guild.me.guild_permissions
        if role and not role.mentionable and not permissions.mention_everyone:
            raise ValueError('Make this role mentionable, or grant me Mention Everyone in the spawn channel.')
        async with self.lock(i.guild_id):
            state = await self.state(i.guild_id)
            state['notify_role'] = role.id if role else None
            await self.save(i.guild_id, state)
        await reply(i, 'Spawn notifications updated', f'New encounters will ping <@&{role.id}>.' if role else 'Spawn role pings are disabled.')

    async def admin_route(self, i, action):
        if action == 'Spawn channel':
            view = View(self, i.user.id)
            view.add_item(ChannelChoice())
            return await reply(i, 'Spawn channel', 'Choose the channel where wild Pokémon should appear.', view)
        if action in {'Settings', 'Enable / disable', 'Orders'}:
            await i.response.defer(ephemeral=True)
            async with self.lock(i.guild_id):
                state = await self.state(i.guild_id)
                if action == 'Enable / disable':
                    if not state['enabled'] and not state['channel']: raise ValueError('Select a spawn channel first.')
                    state['enabled'] = not state['enabled']
                    state['spawn'] = None
                    state['next_spawn'] = time.time() + state['interval']
                    await self.save(i.guild_id, state)
                if action == 'Orders':
                    rows = [f"`{key}` · {o['status']} · {o.get('kind', 'shop')}" for key,o in state['orders'].items() if o['status'] not in {'complete','failed','cancelled'}]
                    return await reply(i, 'Orders requiring review', '\n'.join(rows[-30:]) or 'None. Bank-uncertain records must be reconciled against the bank by the bot owner.')
                return await reply(i, 'Pokémon settings', f"Enabled: {state['enabled']}\nChannel: {state['channel']}\nInterval: {state['interval']//60} minutes\nEncounter duration: 5 minutes\nNotification role: {state['notify_role'] or 'Disabled'}\nRole bonuses: {state['roles']}\nRoles use the highest bonus for each category; bonuses do not stack.")
        fields = {
            'Notification role': [('Role ID', 'Enter a role ID or role mention; 0 disables pings')],
            'Interval': [('Minutes', 'Default 30; minimum 1; maximum 1440')],
            'Role bonuses': [('Role ID', 'Use 0 to clear all role bonuses'), ('Multipliers', 'catch,shiny,rare,xp,candy e.g. 1.2,2,2,1.5,1')],
            'Give Pokémon': [('Member ID', 'Discord member ID'), ('Species', 'Pokédex number or species name')],
            'Take Pokémon': [('Member ID', 'Discord member ID'), ('Pokémon ID', 'ID from their PC box')],
            'Give / take items': [('Member ID', 'Discord member ID'), ('Item', 'e.g. ultra-ball'), ('Amount', 'Positive gives; negative removes')],
            'Force evolve': [('Member ID', 'Discord member ID'), ('Pokémon ID', 'ID from their PC box'), ('Target species', 'Direct evolution name or Pokédex number')],
            'Wipe box': [('Member ID', 'Discord member ID')]
        }
        async def submit(interaction, *values):
            if await self.admin(interaction): await self.admin_action(interaction, action, *values)
        await i.response.send_modal(Input(self, action, fields[action], submit))

    async def admin_action(self, i, action, *values):
        if action == 'Notification role':
            return await self.set_notification_role(i, values[0])
        if action == 'Wipe box':
            uid = int(values[0])
            async def wipe(interaction):
                if not await self.admin(interaction): return
                async with self.lock(i.guild_id):
                    state = await self.state(i.guild_id)
                    self.ensure_unlocked(state, uid)
                    player = account(state, uid)
                    count = len(player['box'])
                    player['box'], player['party'] = {}, []
                    await self.save(i.guild_id, state)
                await reply(interaction, 'Box wiped', f'Removed {count} Pokémon and cleared the party.')
            return await reply(i, 'Permanently wipe box?', f'This removes every Pokémon belonging to member {uid} in this server.', Confirm(self, i.user.id, wipe, 'Wipe PC box'))
        if action in {'Give Pokémon', 'Force evolve'}: await self.dex.load()
        async with self.lock(i.guild_id):
            state = await self.state(i.guild_id)
            if action == 'Interval':
                minutes = int(values[0])
                if not 1 <= minutes <= 1440: raise ValueError('Choose 1–1440 minutes.')
                state['interval'] = minutes*60
                state['next_spawn'] = time.time() + state['interval']
                state['spawn'] = None
            elif action == 'Role bonuses':
                rid = int(values[0])
                if rid == 0: state['roles'] = {}
                else:
                    if i.guild.get_role(rid) is None: raise ValueError('That role is not in this server.')
                    parts = [float(v.strip()) for v in values[1].split(',')]
                    if len(parts) != 5 or any(not math.isfinite(v) for v in parts) or any(not 1 <= v <= 100 for v in parts[:4]) or not 0 <= parts[4] <= 100 or not parts[4].is_integer():
                        raise ValueError('Enter four multipliers from 1 to 100 and an integer extra Candy amount from 0 to 100.')
                    state['roles'][str(rid)] = dict(zip(('catch','shiny','rare','xp','candy'), parts))
            else:
                uid = int(values[0])
                if i.guild.get_member(uid) is None: raise ValueError('Choose a member of this server.')
                self.ensure_unlocked(state, uid)
                player = account(state, uid)
                if action == 'Give Pokémon':
                    p = new_pokemon(self.dex.resolve(values[1]), self.dex)
                    player['box'][p['id']] = p
                elif action == 'Take Pokémon': remove_pokemon(player, values[1])
                elif action == 'Give / take items':
                    item, amount = values[1].lower(), int(values[2])
                    if item not in ITEMS: raise ValueError('Unknown shop item.')
                    if amount == 0 or abs(amount) > 1000000: raise ValueError('Choose a non-zero amount up to 1,000,000.')
                    if player['items'].get(item, 0)+amount < 0: raise ValueError('The member does not have enough of that item.')
                    player['items'][item] = player['items'].get(item, 0)+amount
                elif action == 'Force evolve':
                    p = player['box'].get(values[1])
                    if not p: raise ValueError('That Pokémon is not in this member’s box.')
                    target = self.dex.resolve(values[2])
                    if target['parent'] != p['species']: raise ValueError('Choose a direct evolution.')
                    self.evolve(p, target)
            await self.save(i.guild_id, state)
        await reply(i, 'Settings updated', f'{action} completed.')

    async def purchase(self, i, item, quantity, order_id):
        if item not in ITEMS or not 1 <= quantity <= 999: raise ValueError('Choose a shop item and quantity from 1 to 999.')
        async with self.bank_lock(i.user.id), self.lock(i.guild_id):
            state = await self.available(i.guild_id)
            if order_id in state['orders']: raise ValueError('This purchase was already submitted. Check Orders.')
            if any(o.get('user') == i.user.id and o['status'] not in {'complete','failed','cancelled'} for o in state['orders'].values()):
                raise ValueError('You have an unresolved purchase. Ask the bot owner to review Orders first.')
            self.ensure_unlocked(state, i.user.id)
            order = {'kind': 'shop', 'user': i.user.id, 'item': item, 'quantity': quantity,
                     'price': ITEMS[item]*quantity, 'status': 'charging',
                     'global_bank': await bank.is_global(), 'created': time.time()}
            state['orders'][order_id] = order
            await self.save(i.guild_id, state)
            try:
                await bank.withdraw_credits(i.user, order['price'])
            except ValueError:
                order['status'] = 'failed'
                await self.save(i.guild_id, state)
                raise ValueError('You do not have enough currency.') from None
            except Exception:
                log.exception('Pokémon purchase charge uncertain: %s', order_id)
                raise ValueError(f'Order {order_id} needs owner review; it will not charge again.') from None
            order['status'] = 'charged'
            await self.save(i.guild_id, state)
            player = account(state, i.user.id)
            player['items'][item] = player['items'].get(item, 0)+quantity
            order['status'] = 'complete'
            # Delivery and completion are committed together. Charged orders can be recovered.
            await self.save(i.guild_id, state)
        await reply(i, 'Purchase complete', f'{quantity} × {item} for {order["price"]:,} {await bank.get_currency_name(i.guild)}.\nOrder: `{order_id}`')

    async def offer_trade(self, i, member_id, offered, requested, items, currency):
        target = i.guild.get_member(int(member_id))
        if not target or target.bot or target.id == i.user.id: raise ValueError('Choose another human member of this server.')
        def ids(text): return [] if text.lower() == 'none' else [v.strip() for v in text.split(',')]
        offer, request = {'pokemon': ids(offered), 'items': {}}, {'pokemon': ids(requested), 'items': {}}
        if items.lower() != 'none':
            for entry in items.split(';'):
                side, value = entry.strip().split(':', 1)
                item, quantity = value.split('=', 1)
                if side not in {'offer','request'}: raise ValueError('Items use offer:item=quantity;request:item=quantity.')
                bundle = offer if side == 'offer' else request
                key = item.strip().lower()
                bundle['items'][key] = bundle['items'].get(key, 0)+int(quantity)
        amount = int(currency)
        if abs(amount) > 1000000000: raise ValueError('Currency amount is too large.')
        if not any((offer['pokemon'], request['pokemon'], offer['items'], request['items'], amount)):
            raise ValueError('A trade must include Pokémon, items, or currency.')
        tid = uuid.uuid4().hex[:12]
        async with self.lock(i.guild_id):
            state = await self.available(i.guild_id)
            for uid in (i.user.id, target.id): self.ensure_unlocked(state, uid)
            swap(copy.deepcopy(state), i.user.id, target.id, offer, request)
            # Limit outstanding proposals; no assets are reserved until acceptance.
            state['trades'] = {key:t for key,t in state['trades'].items() if t['expires'] > time.time()}
            if sum(t['from'] == i.user.id for t in state['trades'].values()) >= 10: raise ValueError('You already have ten pending proposals.')
            state['trades'][tid] = {'from': i.user.id, 'to': target.id, 'offer': offer,
                                    'request': request, 'currency': amount, 'expires': time.time()+300}
            await self.save(i.guild_id, state)
        description = (f'<@{i.user.id}> offers a trade to <@{target.id}>.\n'
            f'**They give:** Pokémon {offer["pokemon"]}; items {offer["items"]}\n'
            f'**You give:** Pokémon {request["pokemon"]}; items {request["items"]}\n'
            f'Currency: {abs(amount):,} {await bank.get_currency_name(i.guild)} '
            f'{"from proposer to recipient" if amount >= 0 else "from recipient to proposer"}.\n'
            'Expires in five minutes. Acceptance checks ownership and balances again.')
        await i.channel.send(embed=embed('Trade proposal', description), view=Trade(self, target.id, tid),
                             allowed_mentions=discord.AllowedMentions.none())
        await reply(i, 'Trade offered', f'Proposal `{tid}` posted in this channel.')

    async def finish_trade(self, i, tid, accept):
        # Lock bank users in stable order, then the guild. Shop uses the same lock order.
        initial = (await self.state(i.guild_id))['trades'].get(tid)
        if not initial: raise ValueError('This trade is no longer pending.')
        users = sorted((initial['from'], initial['to']))
        async with self.bank_lock(users[0]), self.bank_lock(users[1]), self.lock(i.guild_id):
            state = await self.available(i.guild_id)
            trade = state['trades'].get(tid)
            if not trade or trade['to'] != i.user.id or trade['expires'] <= time.time(): raise ValueError('This trade is unavailable or expired.')
            if not accept:
                del state['trades'][tid]
                await self.save(i.guild_id, state)
                return await reply(i, 'Trade declined', 'Nothing changed hands.')
            for uid in users: self.ensure_unlocked(state, uid)
            # Complete validation on a copy before touching bank funds or ownership.
            result = copy.deepcopy(state)
            swap(result, trade['from'], trade['to'], trade['offer'], trade['request'])
            amount = trade['currency']
            if amount:
                sender_id, recipient_id = (trade['from'],trade['to']) if amount > 0 else (trade['to'],trade['from'])
                sender, recipient = i.guild.get_member(sender_id), i.guild.get_member(recipient_id)
                if not sender or not recipient: raise ValueError('Both trainers must still be in the server.')
                if not await bank.can_spend(sender, abs(amount)): raise ValueError('The payer has insufficient currency.')
                if await bank.get_balance(recipient)+abs(amount) > await bank.get_max_balance(i.guild): raise ValueError('The recipient’s balance cap would be exceeded.')
                order = {'kind': 'trade', 'users': users, 'currency': amount, 'trade': copy.deepcopy(trade),
                         'status': 'charging', 'created': time.time(), 'global_bank': await bank.is_global()}
                state['orders'][tid] = order
                del state['trades'][tid]
                await self.save(i.guild_id, state)
                try:
                    await bank.withdraw_credits(sender, abs(amount))
                except ValueError:
                    order['status'] = 'failed'
                    await self.save(i.guild_id, state)
                    raise ValueError('The payer no longer has enough currency.') from None
                except Exception:
                    log.exception('Trade debit uncertain: %s', tid)
                    raise ValueError(f'Trade {tid} needs owner bank review. Assets are locked; do not retry.') from None
                order['status'] = 'crediting'
                await self.save(i.guild_id, state)
                try:
                    await bank.deposit_credits(recipient, abs(amount))
                except Exception:
                    log.exception('Trade credit uncertain: %s', tid)
                    raise ValueError(f'Trade {tid} needs owner bank review. Assets are locked; do not retry.') from None
                order['status'] = 'paid'
                await self.save(i.guild_id, state)
                result['orders'] = state['orders']
                result['orders'][tid]['status'] = 'complete'
            result['trades'].pop(tid, None)
            await self.save(i.guild_id, result)
        await reply(i, 'Trade completed', 'Pokémon, items, and currency have been exchanged.')

    @commands.guild_only()
    @commands.is_owner()
    @commands.command(name='pokeorders')
    async def pokeorders(self, ctx):
        """Open owner-only order reconciliation (after checking the bank)."""
        await ctx.send(embed=embed('Order reconciliation',
            'Inspect unresolved orders with pokeset → Orders. Recover safely recorded deliveries, or resolve uncertain bank writes after checking balances. Resolving a currency trade as paid delivers its assets; cancelling does not move currency.'), view=Recovery(self, ctx.author.id))

    async def recover(self, i, oid, decision):
        if not await self.bot.is_owner(i.user): raise ValueError('Only the bot owner can reconcile bank orders.')
        async with self.lock(i.guild_id):
            state = await self.state(i.guild_id)
            order = state['orders'].get(oid)
            if not order or order['status'] in {'complete','failed','cancelled'}: raise ValueError('No unresolved order with that ID.')
            if decision not in {'deliver','cancel'}: raise ValueError('Use deliver or cancel, after checking the bank.')
            if order['global_bank'] != await bank.is_global(): raise ValueError('Restore the original bank mode before reconciling.')
            if decision == 'cancel': order['status'] = 'cancelled'
            elif order['kind'] == 'shop':
                p = account(state, order['user'])
                p['items'][order['item']] = p['items'].get(order['item'],0)+order['quantity']
                order['status'] = 'complete'
            else:
                trade = order['trade']
                swap(state, trade['from'], trade['to'], trade['offer'], trade['request'])
                order['status'] = 'complete'
            order['reviewed_by'] = i.user.id
            order['reviewed_at'] = time.time()
            await self.save(i.guild_id, state)
        await reply(i, 'Order reconciled', f'{oid}: {order["status"]}. No bank transaction was retried.')

    async def red_delete_data_for_user(self, *, requester, user_id):
        for game in set(self.active_battles.values()):
            if user_id in game.players:
                async with game.guard:
                    await game.finish('A trainer’s data was deleted. Battle cancelled.', save=False)
        for gid in await self.config.all_guilds():
            async with self.lock(gid):
                state = await self.state(gid)
                state['players'].pop(str(user_id), None)
                state['trades'] = {k:t for k,t in state['trades'].items() if user_id not in (t['from'],t['to'])}
                state['orders'] = {k:o for k,o in state['orders'].items() if o.get('user') != user_id and user_id not in o.get('users', [])}
                if state['spawn']: state['spawn']['attempts'].pop(str(user_id), None)
                await self.save(gid, state)


class Shop(View):
    def __init__(self, cog, owner):
        super().__init__(cog, owner)
        button = discord.ui.Button(label='Buy items', style=discord.ButtonStyle.success)
        async def buy(i):
            async def details(interaction, item, quantity):
                item, quantity = item.lower(), int(quantity)
                if item not in ITEMS or not 1 <= quantity <= 999: raise ValueError('Choose a listed item and quantity from 1 to 999.')
                oid = uuid.uuid4().hex[:12]
                async def confirm(current): await cog.purchase(current, item, quantity, oid)
                await reply(interaction, 'Confirm purchase', f'{quantity} × {item} costs {ITEMS[item]*quantity:,} {await bank.get_currency_name(i.guild)}.',
                            Confirm(cog, owner, confirm, 'Purchase'))
            await i.response.send_modal(Input(cog, 'Buy items', [('Item', 'e.g. ultra-ball'), ('Quantity', '1–999')], details))
        button.callback = buy
        self.add_item(button)
        button = discord.ui.Button(label='Use healing item')
        async def heal(i):
            async def apply(interaction, pid, item):
                async with cog.lock(i.guild_id):
                    state = await cog.available(i.guild_id)
                    cog.ensure_unlocked(state, owner)
                    player = account(state, owner)
                    p = player['box'].get(pid)
                    if not p: raise ValueError('Choose a Pokémon from your box.')
                    if item not in {'potion','super-potion','hyper-potion','max-potion','revive','max-revive'}: raise ValueError('Choose a potion or revive.')
                    if player['items'].get(item,0) < 1: raise ValueError('You do not have that item.')
                    maximum = stats(p, cog.dex)[0]
                    if item in {'revive','max-revive'}:
                        if p['hp'] > 0: raise ValueError('Revives only work on fainted Pokémon.')
                        p['hp'] = maximum if item == 'max-revive' else max(1, maximum//2)
                    else:
                        if p['hp'] == 0 or p['hp'] >= maximum: raise ValueError('Potions require an injured, non-fainted Pokémon.')
                        p['hp'] = min(maximum, p['hp'] + {'potion':20,'super-potion':60,'hyper-potion':120,'max-potion':maximum}[item])
                    player['items'][item] -= 1
                    await cog.save(i.guild_id, state)
                await reply(interaction, 'Healed', f'{p["name"]}: {p["hp"]}/{maximum} HP')
            await i.response.send_modal(Input(cog, 'Use healing item', [('Pokémon ID','From your box'), ('Item','e.g. potion')], apply))
        button.callback = heal
        self.add_item(button)


class Recovery(View):
    def __init__(self, cog, owner):
        super().__init__(cog, owner)
        button = discord.ui.Button(label='Reconcile order', style=discord.ButtonStyle.danger)
        async def open_modal(i):
            async def details(interaction, oid, decision):
                async def confirm(current): await cog.recover(current, oid, decision.lower())
                await reply(interaction, 'Confirm bank review', f'Order `{oid}` → {decision}. Confirm only after verifying the bank debit/credit. This action changes delivery records and assets; it does not move money.', Confirm(cog, owner, confirm, 'Bank checked; resolve'))
            await i.response.send_modal(Input(cog, 'Reconcile order', [('Order ID','From Orders'), ('Decision','deliver or cancel')], details))
        button.callback = open_modal
        self.add_item(button)

