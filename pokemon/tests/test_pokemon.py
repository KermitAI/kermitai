"""Offline integration tests with strict Discord component and bank doubles."""
import asyncio
import copy
import importlib
import importlib.util
import logging
from pathlib import Path
import random
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).parents[1]
PKG = 'pokemon_test_package'
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]


def decorator(*a, **kw):
    return lambda fn: fn


class Loop:
    def __init__(self, fn): self.fn = fn
    def before_loop(self, fn): return fn
    def start(self): pass
    def cancel(self): pass
    def is_running(self): return True
    def failed(self): return False


class View:
    def __init__(self, **kwargs): self.children = []
    def add_item(self, item):
        if len(self.children) >= 25: raise ValueError('Too many components')
        item.view = self
        self.children.append(item)
    def stop(self): pass


class Component:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        if 'options' in kwargs and not 1 <= len(kwargs['options']) <= 25:
            raise ValueError('Discord selects allow 1–25 options')
        self.values = []


class Embed(Component):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fields=[]
    def add_field(self, **kwargs): self.fields.append(types.SimpleNamespace(**kwargs))
    def set_thumbnail(self, **kwargs): self.thumbnail=kwargs
    def set_image(self, **kwargs): self.image=kwargs
    def set_footer(self, **kwargs): self.footer=kwargs


bank = types.SimpleNamespace()
modules = {
    PKG: pkg,
    'discord': types.SimpleNamespace(ui=types.SimpleNamespace(View=View, Modal=View, Button=Component,
        Select=Component, TextInput=Component, ChannelSelect=Component, RoleSelect=Component), SelectOption=Component,
        Embed=Embed, utils=types.SimpleNamespace(escape_markdown=lambda text:text), ButtonStyle=types.SimpleNamespace(danger=1, success=2, secondary=3),
        ChannelType=types.SimpleNamespace(text=0), Status=types.SimpleNamespace(offline='offline'),
        InteractionResponseType=types.SimpleNamespace(deferred_channel_message=5),
        HTTPException=type('HTTPException',(Exception,),{}),
        NotFound=type('NotFound',(Exception,),{}),
        AllowedMentions=type('AllowedMentions',(Component,),{'none':staticmethod(lambda:None)})),
    'discord.ext': types.SimpleNamespace(tasks=types.SimpleNamespace(loop=lambda **kw:lambda fn:Loop(fn))),
    'redbot': types.ModuleType('redbot'),
    'redbot.core': types.SimpleNamespace(Config=object, bank=bank, commands=types.SimpleNamespace(
        Cog=object, guild_only=decorator, bot_has_permissions=decorator, command=decorator,
        admin_or_permissions=decorator, mod_or_permissions=decorator, is_owner=decorator)),
    'redbot.core.data_manager': types.SimpleNamespace(cog_data_path=lambda cog: ROOT),
    'aiohttp': types.ModuleType('aiohttp'),
}
with patch.dict(sys.modules, modules):
    rules = importlib.import_module(PKG+'.rules')
    game = importlib.import_module(PKG+'.pokemon')
    battle = importlib.import_module(PKG+'.battle')
    dex_module = importlib.import_module(PKG+'.dex')
    storage_module = importlib.import_module(PKG+'.storage')


def state():
    return {'enabled':True, 'channel':5, 'interval':1800, 'next_spawn':0, 'spawn':None,
            'roles':{}, 'players':{}, 'trades':{}, 'orders':{}}


def pokemon(pid='abc', sid=1):
    return {'id':pid, 'species':sid, 'pokemon_id':sid, 'name':'bulbasaur', 'level':20,
            'ivs':[31]*6, 'evs':[0]*6, 'nature':'hardy', 'hp':55, 'moves':[33],
            'height':.7, 'weight':6.9, 'shiny':False}


def dex():
    p = {'stats':[45,49,49,65,65,45], 'effort':[0,0,0,1,0,0], 'types':['grass','poison']}
    species = {**p, 'id':1, 'pokemon_id':1, 'name':'bulbasaur', 'height':7, 'weight':69,
               'capture_rate':45,'family':1,'parent':0,'legendary':False,'mythical':False}
    return types.SimpleNamespace(species={1:species},pokemon={1:p},natures={'hardy':(1,1),'adamant':(1,3)},
        moves={33:{'name':'tackle','type':'normal','class':2,'power':40,'pp':35,'accuracy':100,'priority':0,'effect':1},
               165:{'name':'struggle','type':'normal','class':2,'power':50,'pp':1,'accuracy':100,'priority':0,'effect':255}},
        efficacy={}, learned_moves=lambda pid,level:[33])


class Value:
    def __init__(self, value): self.value=copy.deepcopy(value)
    async def __call__(self, default=...): return copy.deepcopy(self.value)
    async def set(self, value): self.value=copy.deepcopy(value)


class SnapshotValue:
    """Read/write test snapshots through the same global store as production."""
    def __init__(self, cog, gid=1): self.cog,self.gid=cog,gid
    async def __call__(self, default=...): return await self.cog.state(self.gid)
    async def set(self, state):
        world=await self.cog.storage.world()
        for key in storage_module.SHARED: world[key]=copy.deepcopy(state.get(key,{}))
        world['interval']=state.get('interval',1800)
        world['guilds'][str(self.gid)]={k:copy.deepcopy(v) for k,v in state.items() if k not in storage_module.SHARED and k!='interval'}
        await self.cog.config.world.set(world)


class RedMergeValue(Value):
    """Reproduce Red Group's recursive default merge, including dict-vs-None."""
    @classmethod
    def merge(cls, current, defaults):
        for key, value in current.items():
            if isinstance(value, dict):
                defaults[key] = cls.merge(value, defaults.get(key, {}))
            else:
                defaults[key] = copy.deepcopy(value)
        return defaults

    async def __call__(self, default=...):
        defaults = game.default_state() if default is ... else copy.deepcopy(default)
        return self.merge(copy.deepcopy(self.value), defaults)


class RulesTests(unittest.TestCase):
    def test_reserved_families_never_spawn(self):
        for sid in rules.PSEUDOS:
            self.assertFalse(rules.wild_allowed({'id':sid,'legendary':False,'mythical':False}))
        for flag in ('legendary','mythical'):
            p={'id':1,'legendary':False,'mythical':False}; p[flag]=True
            self.assertFalse(rules.wild_allowed(p))

    def test_neutral_nature_does_not_boost_stats(self):
        self.assertEqual(rules.stats(pokemon(),dex()),[54,30,30,37,37,29])
        p=pokemon(); p['nature']='adamant'
        self.assertEqual(rules.stats(p,dex()),[54,33,30,33,37,29])

    def test_hidden_power_uses_cartridge_order(self):
        self.assertEqual(rules.hidden_power([0]*6),'fighting')
        self.assertEqual(rules.hidden_power([31]*6),'dark')
        self.assertEqual(rules.hidden_power([0,0,0,0,0,1]),'flying')

    def test_bonus_highest_per_stat_not_stacked(self):
        s=state(); s['roles']={'1':{'catch':2,'xp':1.5},'2':{'catch':3,'candy':2}}
        self.assertEqual(rules.bonus(s,[1,2])['catch'],3)
        self.assertEqual(rules.bonus(s,[1,2])['xp'],1.5)

    def test_transfer_clears_party_awards_shared_candy(self):
        s=state(); p=rules.account(s,1); p['box']['abc']=pokemon(); p['party']=['abc']
        rules.transfer(p,'abc',1)
        self.assertEqual(p['party'],[]); self.assertEqual(p['candy'],{'1':1})
        with self.assertRaises(ValueError): rules.transfer(p,'abc',1)

    def test_trade_validation_precedes_all_mutations(self):
        s=state(); p=rules.account(s,1); p['box']['abc']=pokemon()
        a={'pokemon':['abc'],'items':{}}; b={'pokemon':['missing'],'items':{}}
        before=copy.deepcopy(s)
        with self.assertRaises(ValueError): rules.swap(s,1,2,a,b)
        # account creation is harmless, but offered assets must remain untouched.
        self.assertEqual(s['players']['1'], before['players']['1'])

    def test_trade_moves_items_and_party_atomically(self):
        s=state(); a=rules.account(s,1); b=rules.account(s,2)
        a['box']['abc']=pokemon(); a['party']=['abc']; b['items']['potion']=2
        rules.swap(s,1,2,{'pokemon':['abc'],'items':{}},{'pokemon':[],'items':{'potion':2}})
        self.assertIn('abc',b['box']); self.assertEqual(a['party'],[])
        self.assertEqual(a['items']['potion'],2)

    def test_failed_trade_with_duplicate_ids(self):
        s=state(); rules.account(s,1)['box']['abc']=pokemon()
        with self.assertRaises(ValueError): rules.swap(s,1,2,{'pokemon':['abc','abc'],'items':{}},{'pokemon':[],'items':{}})

    def test_ball_chances_and_master_ball(self):
        d=dex(); p=pokemon(); a=rules.account(state(),1); perks=rules.bonus(state(),[])
        chance=rules.catch_chance('poke-ball',p,d.species[1],a,perks)
        self.assertGreater(rules.catch_chance('ultra-ball',p,d.species[1],a,perks),chance)
        self.assertEqual(rules.catch_chance('master-ball',p,d.species[1],a,perks),1)

    def test_type_immunity_and_supported_moves(self):
        d=dex(); d.efficacy[('normal','grass')]=0
        self.assertEqual(battle.damage(pokemon(),pokemon(),d.moves[33],d),0)
        self.assertTrue(battle.supported(d.moves[33]))
        self.assertFalse(battle.supported({**d.moves[33],'effect':2}))


class GlobalStorageTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, legacy):
        self.sources={gid:Value(value) for gid,value in legacy.items()}
        self.world=Value({})
        config=types.SimpleNamespace(world=self.world,
            all_guilds=AsyncMock(return_value={gid:{} for gid in legacy}),
            guild_from_id=lambda gid:types.SimpleNamespace(state=self.sources[gid]))
        return storage_module.GlobalStore(config)

    async def test_migration_combines_assets_and_is_repeat_safe(self):
        a,b=state(),state()
        one=rules.account(a,1); two=rules.account(b,1)
        one.update(xp=100,dust=200,last_pokestop=900)
        two.update(xp=50,dust=70,last_pokestop=1000)
        one['box']['a']=pokemon('a'); one['party']=['a']
        two['box']['b']=pokemon('b'); two['party']=['b']
        one['items']['potion']=2; two['items']['potion']=3
        one['candy']['1']=4; two['candy']['1']=6
        rules.record_catch(one,one['box']['a']);rules.record_catch(two,two['box']['b'])
        a['roles']={'123':{'catch':2}};b['roles']={'456':{'xp':3}}
        a['channel']=5;b['channel']=8
        store=self.fixture({1:a,2:b})
        world=await store.world(); player=world['players']['1']
        self.assertEqual(player['xp'],150);self.assertEqual(player['dust'],270)
        self.assertEqual(player['items']['potion'],5);self.assertEqual(player['candy']['1'],10)
        self.assertEqual(set(player['box']),{'a','b'});self.assertEqual(player['party'],['a'])
        self.assertEqual(player['pokedex']['1']['caught'],2)
        self.assertEqual(player['last_pokestop'],1000)
        self.assertEqual((await store.read(1))['roles'],a['roles'])
        self.assertEqual((await store.read(2))['channel'],8)
        self.assertEqual(await store.world(),world)
        # A new store instance simulates a process restart; migration must not double assets.
        self.assertEqual(await storage_module.GlobalStore(store.config).world(),world)

    async def test_id_collisions_preserve_both_pokemon_and_party_references(self):
        a,b=state(),state()
        for s in (a,b):
            p=rules.account(s,1);p['box']['same']=pokemon('same');p['party']=['same']
        store=self.fixture({1:a,2:b})
        world=await store.world();p=world['players']['1']
        self.assertEqual(len(p['box']),2)
        self.assertTrue(all(pid==mon['id'] for pid,mon in p['box'].items()))
        self.assertIn(p['party'][0],p['box'])

    async def test_global_interval_updates_all_schedules_keeps_local_settings(self):
        a,b=state(),state();a['interval']=300;b['interval']=600
        store=self.fixture({1:a,2:b})
        self.assertEqual((await store.read(1))['interval'],1800)
        s=await store.read(1);s['interval']=300
        with patch('time.time',return_value=1000): await store.save(1,s)
        for gid in (1,2):
            loaded=await store.read(gid)
            self.assertEqual(loaded['interval'],300)
            self.assertEqual(loaded['next_spawn'],1300)
        self.assertEqual((await store.read(2))['channel'],b['channel'])

    async def test_delete_scrubs_global_records_and_legacy_backups(self):
        a=state();rules.account(a,1)['box']['a']=pokemon('a')
        a['pending_spawn_edits']={'old':{'spawn':{'attempts':{'1':{'count':1}}}}}
        store=self.fixture({1:a});await store.world()
        await store.delete_user(1)
        self.assertNotIn('1',(await store.world())['players'])
        self.assertNotIn('1',(await self.sources[1]())['players'])
        self.assertEqual((await store.read(1))['pending_spawn_edits']['old']['spawn']['attempts'],{})
        self.assertNotIn('1',(await storage_module.GlobalStore(store.config).world())['players'])


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog=object.__new__(game.Pokemon)
        self.legacy_value=Value(state())
        self.global_value=Value({})
        self.cog.config=types.SimpleNamespace(world=self.global_value,guild_from_id=lambda gid:types.SimpleNamespace(state=self.legacy_value),
                                           all_guilds=AsyncMock(return_value={1:{}}))
        self.cog.storage=storage_module.GlobalStore(self.cog.config)
        self.value=SnapshotValue(self.cog)
        self.cog.locks={}; self.cog.bank_locks={}; self.cog.active_battles={}; self.cog.views=set(); self.cog.expiry_tasks={}; self.cog.last_errors={}
        self.cog.dex=dex()
        self.user=types.SimpleNamespace(id=1,roles=[],display_name='Trainer One',name='one',display_avatar=types.SimpleNamespace(url='https://example.com/one.png'),guild_permissions=types.SimpleNamespace(administrator=False,manage_guild=False,manage_messages=False))
        self.other=types.SimpleNamespace(id=2,roles=[],display_name='Trainer Two',name='two',display_avatar=types.SimpleNamespace(url='https://example.com/two.png'))
        self.guild=types.SimpleNamespace(id=1,get_member=lambda uid:{1:self.user,2:self.other}.get(uid), get_channel=lambda cid:None)
        self.user.guild=self.guild; self.other.guild=self.guild
        self.guild.members=[self.user,self.other]
        self.cog.bot=types.SimpleNamespace(get_cog=lambda n:self.cog,get_guild=lambda gid:self.guild,
            cog_disabled_in_guild=AsyncMock(return_value=False),is_owner=AsyncMock(return_value=True))
        self.i=types.SimpleNamespace(guild_id=1,guild=self.guild,user=self.user,
            response=types.SimpleNamespace(type=6,is_done=lambda:True,defer=AsyncMock(),send_modal=AsyncMock()),followup=types.SimpleNamespace(send=AsyncMock()))
        bank.is_global=AsyncMock(return_value=False)
        bank.withdraw_credits=AsyncMock(); bank.deposit_credits=AsyncMock()
        bank.get_currency_name=AsyncMock(return_value='Coins')
        bank.can_spend=AsyncMock(return_value=True); bank.get_balance=AsyncMock(return_value=1000)
        bank.get_max_balance=AsyncMock(return_value=1000000)

    async def test_component_option_limits(self):
        view=game.Catch(self.cog,1,'spawn')
        ball_options=sum(len(c.options) for c in view.children if hasattr(c,'options') and c.placeholder != 'Optional berry')
        self.assertEqual(ball_options,len(rules.BALLS))
        game.Menu(self.cog,1)
        admin_menu=game.Menu(self.cog,1,admin=True)
        self.assertEqual(len(admin_menu.children),13)
        self.assertTrue(all(hasattr(child,'label') and not hasattr(child,'options') for child in admin_menu.children))
        self.cog.route=AsyncMock()
        for button in admin_menu.children:
            await button.callback(self.i)
            self.cog.route.assert_awaited_with(self.i,button.label,admin=True)

    async def test_simultaneous_catch_has_one_winner(self):
        s=state(); s['spawn']={'id':'spawn','pokemon':pokemon(),'spawned_at':time_now(),'expires':time_now()+100,'attempts':{},'message':10}
        rules.account(s,1)['items']['master-ball']=1
        rules.account(s,2)['items']['master-ball']=1
        await self.value.set(s)
        other=copy.copy(self.i); other.user=self.other
        results=await asyncio.gather(self.cog.catch(self.i,'spawn','master-ball',None),
                                    self.cog.catch(other,'spawn','master-ball',None),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,str) for r in results),1)
        stored=await self.value()
        self.assertIsNone(stored['spawn'])
        self.assertEqual(sum(len(p['box']) for p in stored['players'].values()),1)
        self.assertEqual(sum(p['items'].get('master-ball',0) for p in stored['players'].values()),1)

    async def test_shop_repeat_does_not_charge_twice(self):
        await self.cog.purchase(self.i,'ultra-ball',2,'order')
        with self.assertRaises(ValueError): await self.cog.purchase(self.i,'ultra-ball',2,'order')
        self.assertEqual(bank.withdraw_credits.await_count,1)
        self.assertEqual((await self.value())['players']['1']['items']['ultra-ball'],2)

    async def test_shop_uncertain_debit_blocks_retry(self):
        bank.withdraw_credits.side_effect=RuntimeError('failed after debit')
        with self.assertLogs('red.pokemon',level='ERROR'):
            with self.assertRaises(ValueError): await self.cog.purchase(self.i,'potion',1,'order')
        with self.assertRaises(ValueError): await self.cog.purchase(self.i,'potion',1,'another')
        self.assertEqual(bank.withdraw_credits.await_count,1)
        self.assertEqual((await self.value())['orders']['order']['status'],'charging')

    async def test_recovery_delivers_once_without_recharging(self):
        s=state(); s['orders']['order']={'kind':'shop','user':1,'item':'potion','quantity':2,'status':'charged','global_bank':False}
        await self.value.set(s)
        await self.cog.recover(self.i,'order','deliver')
        with self.assertRaises(ValueError): await self.cog.recover(self.i,'order','deliver')
        self.assertEqual((await self.value())['players']['1']['items']['potion'],2)
        bank.withdraw_credits.assert_not_awaited()

    async def test_uncertain_trade_locks_both_collections(self):
        s=state(); s['orders']['o']={'kind':'trade','users':[1,2],'status':'crediting'}
        for uid in (1,2):
            with self.assertRaises(ValueError): self.cog.ensure_unlocked(s,uid)

    async def test_trade_payment_and_assets_complete_together(self):
        s=state(); rules.account(s,1)['box']['abc']=pokemon()
        s['trades']['t']={'from':1,'to':2,'offer':{'pokemon':['abc'],'items':{}},
                         'request':{'pokemon':[],'items':{}},'currency':100,'guild_id':1,'expires':time_now()+100}
        await self.value.set(s); self.i.user=self.other
        await self.cog.finish_trade(self.i,'t',True)
        stored=await self.value()
        self.assertEqual(stored['orders']['t']['status'],'complete')
        self.assertIn('abc',stored['players']['2']['box'])
        bank.withdraw_credits.assert_awaited_once_with(self.user,100)
        bank.deposit_credits.assert_awaited_once_with(self.other,100)
        with self.assertRaises(ValueError): await self.cog.finish_trade(self.i,'t',True)

    async def test_trade_credit_failure_preserves_ownership_and_locks(self):
        s=state(); rules.account(s,1)['box']['abc']=pokemon()
        s['trades']['t']={'from':1,'to':2,'offer':{'pokemon':['abc'],'items':{}},
                         'request':{'pokemon':[],'items':{}},'currency':100,'guild_id':1,'expires':time_now()+100}
        await self.value.set(s); self.i.user=self.other
        bank.deposit_credits.side_effect=RuntimeError('bank offline')
        with self.assertLogs('red.pokemon',level='ERROR'):
            with self.assertRaises(ValueError): await self.cog.finish_trade(self.i,'t',True)
        stored=await self.value()
        self.assertIn('abc',stored['players']['1']['box'])
        self.assertEqual(stored['orders']['t']['status'],'crediting')
        with self.assertRaises(ValueError): self.cog.ensure_unlocked(stored,1)

    async def test_disabled_feature_rejects_stale_catch(self):
        s=state(); s['enabled']=False; await self.value.set(s)
        with self.assertRaises(ValueError): await self.cog.catch(self.i,'old','poke-ball',None)

    async def test_battle_resolves_both_actions_and_spends_pp(self):
        teams={1:[pokemon(str(j)) for j in range(6)],2:[pokemon(str(j+10)) for j in range(6)]}
        match=battle.Battle(self.cog,1,teams)
        match.message=types.SimpleNamespace(edit=AsyncMock())
        match.choices={1:('move',33),2:('move',33)}
        await match.resolve()
        self.assertEqual(match.turn,2)
        self.assertLess(teams[1][0]['hp'],55)
        self.assertLess(teams[2][0]['hp'],55)
        self.assertEqual(match.pp['0'][33],34)
        self.assertEqual(match.pp['10'][33],34)

    async def test_old_battle_choice_does_not_enter_next_turn(self):
        teams={1:[pokemon(str(j)) for j in range(6)],2:[pokemon(str(j+10)) for j in range(6)]}
        match=battle.Battle(self.cog,1,teams)
        match.turn=2
        self.i.response.defer=AsyncMock()
        await match.submit(self.i,('move',33),1)
        self.assertEqual(match.choices,{})

    async def test_battle_finish_preserves_new_inventory(self):
        teams={1:[pokemon(str(j)) for j in range(6)],2:[pokemon(str(j+10)) for j in range(6)]}
        s=state()
        for uid,team in teams.items():
            player=rules.account(s,uid)
            player['box']={p['id']:copy.deepcopy(p) for p in team}
            player['items']['potion']=5
        await self.value.set(s)
        match=battle.Battle(self.cog,1,teams)
        for uid in teams: self.cog.active_battles[(1,uid)]=match
        teams[1][0]['hp']=10
        teams[1][0]['evs'][3]=1
        await match.finish('Finished',save=True)
        stored=await self.value()
        self.assertEqual(stored['players']['1']['box']['0']['hp'],10)
        self.assertEqual(stored['players']['1']['box']['0']['evs'][3],1)
        self.assertEqual(stored['players']['1']['items']['potion'],5)
        self.assertFalse(self.cog.active_battles)

    async def test_pokestop_awards_supplies_and_dust_without_bank_payment(self):
        with patch.object(game.time,'time',return_value=1000):
            items,dust=await self.cog.spin_stop(1,1)
        stored=await self.value()
        self.assertTrue(3 <= sum(items.values()) <= 6)
        self.assertTrue(50 <= dust <= 150)
        self.assertEqual(stored['players']['1']['dust'],dust)
        self.assertEqual(stored['players']['1']['last_pokestop'],1000)
        for item,quantity in items.items():
            self.assertIn(item,rules.ITEMS)
            self.assertEqual(stored['players']['1']['items'][item],quantity+(20 if item=='poke-ball' else 0))
        bank.withdraw_credits.assert_not_awaited()

    async def test_pokestop_concurrent_spins_only_reward_once(self):
        with patch.object(game.time,'time',return_value=1000):
            results=await asyncio.gather(self.cog.spin_stop(1,1),self.cog.spin_stop(1,1),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,tuple) for r in results),1)
        self.assertEqual(sum(isinstance(r,ValueError) for r in results),1)

    async def test_pokestop_cooldown_survives_existing_accounts_and_boundary(self):
        s=state(); old=rules.account(s,1); old.pop('last_pokestop')
        await self.value.set(s)
        with patch.object(game.time,'time',return_value=1000): await self.cog.spin_stop(1,1)
        snapshot=await self.value()
        with patch.object(game.time,'time',return_value=1299.9):
            with self.assertRaisesRegex(ValueError,'1 seconds'): await self.cog.spin_stop(1,1)
        self.assertEqual(await self.value(),snapshot)
        with patch.object(game.time,'time',return_value=1300): await self.cog.spin_stop(1,1)
        self.assertEqual((await self.value())['players']['1']['last_pokestop'],1300)

    async def test_pokestop_disabled_and_trade_locks_prevent_rewards(self):
        s=state(); s['enabled']=False; await self.value.set(s)
        with self.assertRaises(ValueError): await self.cog.spin_stop(1,1)
        s['enabled']=True; s['orders']['t']={'kind':'trade','users':[1,2],'status':'crediting'}
        await self.value.set(s)
        with self.assertRaises(ValueError): await self.cog.spin_stop(1,1)
        self.assertEqual((await self.value())['players'],{})

    async def test_pokestop_users_have_independent_cooldowns(self):
        with patch.object(game.time,'time',return_value=1000):
            await self.cog.spin_stop(1,1)
            await self.cog.spin_stop(1,2)
        self.assertEqual(len((await self.value())['players']),2)

    async def test_expiry_clears_encounter_and_removes_public_buttons(self):
        s=state(); s['spawn']={'id':'s','pokemon':pokemon(),'spawned_at':100,
                              'expires':220,'channel':5,'message':10,'attempts':{}}
        await self.value.set(s)
        message=types.SimpleNamespace(edit=AsyncMock())
        self.guild.get_channel=lambda cid:types.SimpleNamespace(get_partial_message=lambda mid:message)
        with patch.object(game.time,'time',return_value=400):
            self.assertTrue(await self.cog.expire_spawn(1,'s'))
        self.assertIsNone((await self.value())['spawn'])
        self.assertIsNone(message.edit.call_args.kwargs['view'])
        self.assertEqual(message.edit.call_args.kwargs['embed'].title,'The wild Pokémon fled!')
        self.assertIn('fled',message.edit.call_args.kwargs['embed'].description)
        self.assertTrue(message.edit.call_args.kwargs['embed'].image['url'].endswith('/1.png'))
        self.assertEqual((await self.cog.state(1))['pending_spawn_edits'],{})
        self.assertFalse(await self.cog.expire_spawn(1,'s'))
        message.edit.assert_awaited_once()

    async def test_old_timer_cannot_remove_new_encounter(self):
        s=state(); s['spawn']={'id':'new','pokemon':pokemon(),'spawned_at':100,'expires':220,'message':10}
        await self.value.set(s)
        with patch.object(game.time,'time',return_value=500):
            self.assertFalse(await self.cog.expire_spawn(1,'old'))
        self.assertEqual((await self.value())['spawn']['id'],'new')

    async def test_no_early_flee_and_exact_cutoff_rejects_catch_without_consuming_ball(self):
        s=state(); s['spawn']={'id':'s','pokemon':pokemon(),'spawned_at':100,'expires':220,'message':10}
        rules.account(s,1)['items']['master-ball']=1; await self.value.set(s)
        with patch.object(game.time,'time',return_value=219.99):
            self.assertFalse(await self.cog.expire_spawn(1,'s'))
        with patch.object(game.time,'time',return_value=220):
            with self.assertRaises(ValueError): await self.cog.catch(self.i,'s','master-ball',None)
            with self.assertRaises(ValueError): await self.cog.current_encounter(1,5)
        self.assertEqual((await self.value())['players']['1']['items']['master-ball'],1)

    async def test_old_encounter_migrates_to_two_minutes(self):
        s=state(); s['next_spawn']=1900
        s['spawn']={'id':'s','pokemon':pokemon(),'expires':1900,'message':10}
        await self.value.set(s)
        self.assertEqual((await self.cog.state(1))['spawn']['expires'],220)
        self.assertIsNone((await self.cog.state(1))['notify_role'])

    async def test_catch_command_encounter_requires_spawn_channel(self):
        s=state(); s['spawn']={'id':'s','pokemon':pokemon(),'spawned_at':time_now(),'expires':time_now()+100,'message':10}
        await self.value.set(s)
        with self.assertRaisesRegex(ValueError,'<#5>'): await self.cog.current_encounter(1,6)
        self.assertEqual((await self.cog.current_encounter(1,5))['id'],'s')

    async def test_spawn_duration_and_role_ping_are_independent_of_interval(self):
        role=types.SimpleNamespace(id=123,mentionable=True,managed=False,is_default=lambda:False)
        channel=types.SimpleNamespace(id=5,send=AsyncMock(return_value=types.SimpleNamespace(id=10)))
        self.guild.get_channel=lambda cid:channel
        self.guild.get_role=lambda rid:role
        self.guild.members=[]
        self.cog.spawn_view=game.Spawn(self.cog)
        self.cog.schedule_expiry=Mock()
        s=state(); s['notify_role']=123; await self.value.set(s)
        with patch.object(game.time,'time',return_value=1000): await self.cog.spawn(1)
        stored=await self.value()
        self.assertEqual(stored['spawn']['expires'],1120)
        self.assertEqual(stored['next_spawn'],2800)
        sent=channel.send.call_args.kwargs
        self.assertEqual(sent['content'],'<@&123>')
        self.assertTrue(sent['embed'].image['url'].endswith('/1.png'))
        self.assertEqual(sent['allowed_mentions'].roles,[role])
        self.assertFalse(sent['allowed_mentions'].everyone)
        self.assertFalse(sent['allowed_mentions'].users)
        self.cog.schedule_expiry.assert_called_once()

    async def test_spawn_does_not_ping_deleted_or_unmentionable_role(self):
        channel=types.SimpleNamespace(id=5,send=AsyncMock(return_value=types.SimpleNamespace(id=10)),
            permissions_for=lambda member:types.SimpleNamespace(mention_everyone=False))
        self.guild.get_channel=lambda cid:channel
        self.guild.members=[]; self.guild.me=object()
        self.cog.spawn_view=game.Spawn(self.cog); self.cog.schedule_expiry=Mock()
        for role in (None,types.SimpleNamespace(id=123,mentionable=False,managed=False,is_default=lambda:False)):
            self.guild.get_role=lambda rid:role
            s=state(); s['notify_role']=123; await self.value.set(s)
            await self.cog.spawn(1)
            self.assertIsNone(channel.send.call_args.kwargs['content'])
            self.assertEqual(channel.send.call_args.kwargs['allowed_mentions'].roles,[])

    async def test_notification_role_can_be_set_and_cleared(self):
        role=types.SimpleNamespace(id=123,mentionable=True,managed=False,is_default=lambda:False)
        self.guild.get_role=lambda rid:role
        self.guild.me=types.SimpleNamespace(guild_permissions=types.SimpleNamespace(mention_everyone=False))
        await self.cog.set_notification_role(self.i,'123')
        self.assertEqual((await self.value())['notify_role'],123)
        await self.cog.set_notification_role(self.i,'0')
        self.assertIsNone((await self.value())['notify_role'])

    async def test_restart_rearms_existing_expiry_without_resetting_deadline(self):
        s=state(); s['next_spawn']=1900
        s['spawn']={'id':'s','pokemon':pokemon(),'expires':1900,'message':10}
        await self.value.set(s)
        self.cog.bot.wait_until_red_ready=AsyncMock()
        self.cog.schedule_expiry=Mock()
        await self.cog.before_scheduler()
        self.assertEqual(self.cog.schedule_expiry.call_args.args[1]['expires'],220)

    async def test_expiry_task_expires_and_cleans_up_its_registry(self):
        s=state(); s['spawn']={'id':'s','pokemon':pokemon(),'spawned_at':100,'expires':220,'message':10}
        await self.value.set(s)
        with patch.object(game.time,'time',return_value=400):
            self.cog.schedule_expiry(1,s['spawn'])
            task=self.cog.expiry_tasks[1]
            # Scheduling the same live encounter does not create a second timer.
            self.cog.schedule_expiry(1,s['spawn'])
            self.assertIs(self.cog.expiry_tasks[1],task)
            await task
        self.assertEqual(self.cog.expiry_tasks,{})
        self.assertIsNone((await self.value())['spawn'])

    async def test_notification_role_callback_requires_admin(self):
        self.cog.bot.is_owner=AsyncMock(return_value=False)
        self.cog.bot.is_admin=AsyncMock(return_value=False)
        self.user.guild_permissions=types.SimpleNamespace(administrator=False)
        await self.cog.set_notification_role(self.i,'123')
        self.assertIsNone((await self.value())['notify_role'])

    async def test_settings_toggle_orders_reply_without_invalid_null_views(self):
        async def strict_send(**kwargs):
            if 'view' in kwargs and kwargs['view'] is None:
                raise TypeError('expected View not NoneType')
        self.i.followup.send.side_effect=strict_send
        menu=game.Menu(self.cog,1,admin=True)
        for action in ('Settings','Enable / disable','Orders'):
            button=next(b for b in menu.children if b.label==action)
            await button.callback(self.i)
            self.i.response.defer.assert_awaited_with(ephemeral=True,thinking=True)
            sent=self.i.followup.send.call_args.kwargs
            if action=='Settings':
                self.assertIsInstance(sent['view'],game.Menu)
            else:
                self.assertNotIn('view',sent)
        self.assertFalse((await self.value())['enabled'])
        await next(b for b in menu.children if b.label=='Enable / disable').callback(self.i)
        self.assertTrue((await self.value())['enabled'])

    async def test_trainer_card_uses_target_balance_nickname_and_unique_species(self):
        s=state(); player=rules.account(s,2)
        player['box']={'a':pokemon('a',1),'b':pokemon('b',1),'c':pokemon('c',2)}
        await self.value.set(s)
        card=await self.cog.trainer_card(self.other)
        fields={f.name:f.value for f in card.fields}
        self.assertIn('Trainer Two',card.description)
        self.assertEqual(fields['Money'],'1,000 Coins')
        self.assertEqual(fields['Pokédex'],'2 unique species')
        self.assertEqual(fields['Pokémon owned'],'3')
        bank.get_balance.assert_awaited_once_with(self.other)
        self.assertEqual(card.thumbnail['url'],self.other.display_avatar.url)

    async def test_other_trainer_card_does_not_change_or_create_accounts(self):
        before=await self.value()
        await self.cog.show_trainer(self.i,self.other)
        self.assertIn('Trainer Two',self.i.followup.send.call_args.kwargs['embed'].description)
        self.assertEqual(await self.value(),before)

    async def test_member_lookup_accepts_mention_and_rejects_ambiguous_names(self):
        self.assertIs(self.cog.resolve_member(self.guild,'<@!2>'),self.other)
        self.assertIs(self.cog.resolve_member(self.guild,'Trainer Two'),self.other)
        self.other.display_name='Trainer One'
        with self.assertRaisesRegex(ValueError,'multiple'): self.cog.resolve_member(self.guild,'Trainer One')

    async def test_staff_box_is_private_and_labels_target_owner(self):
        s=state(); rules.account(s,2)['box']['abc']=pokemon(); await self.value.set(s)
        await self.cog.show_member_box(self.i,self.other)
        sent=self.i.followup.send.call_args.kwargs
        self.assertTrue(sent['ephemeral'])
        self.assertIn('Trainer Two',sent['embed'].title)
        self.assertIn('abc',sent['embed'].description)
        self.assertEqual(sent['view'].owner,1)
        self.assertTrue(sent['view'].staff_only)
        self.cog.bot.is_owner.return_value=False
        self.cog.bot.is_admin=AsyncMock(return_value=False)
        self.cog.bot.is_mod=AsyncMock(return_value=False)
        self.assertFalse(await sent['view'].interaction_check(self.i))

    async def test_nonstaff_cannot_open_another_box(self):
        self.cog.bot.is_owner.return_value=False
        self.cog.bot.is_admin=AsyncMock(return_value=False)
        self.cog.bot.is_mod=AsyncMock(return_value=False)
        s=state(); rules.account(s,2)['box']['secret']=pokemon(); await self.value.set(s)
        await self.cog.show_member_box(self.i,self.other)
        sent=self.i.followup.send.call_args.kwargs
        self.assertEqual(sent['embed'].title,'Staff only')
        self.assertNotIn('secret',sent['embed'].description)
        self.assertNotIn('view',sent)

    async def test_spawn_click_acknowledges_before_loading_and_opens_catch(self):
        self.i.message=types.SimpleNamespace(id=10)
        self.i.channel_id=5
        async def read_encounter(gid,cid):
            self.i.response.defer.assert_awaited_once_with(ephemeral=True,thinking=True)
            return {'id':'s','message':10}
        self.cog.current_encounter=AsyncMock(side_effect=read_encounter)
        await game.Spawn(self.cog).open(self.i)
        sent=self.i.followup.send.call_args.kwargs
        self.assertEqual(sent['embed'].title,'Choose a ball')
        self.assertIsInstance(sent['view'],game.Catch)
        self.assertEqual(sent['view'].spawn_id,'s')
        self.assertEqual(sent['view'].owner,1)

    async def test_spawn_click_rejects_old_message_without_opening_menu(self):
        self.i.channel_id=5
        self.cog.current_encounter=AsyncMock(return_value={'id':'new','message':20})
        await self.cog.open_catch(self.i,message_id=10)
        sent=self.i.followup.send.call_args.kwargs
        self.assertEqual(sent['embed'].title,'Cannot catch')
        self.assertNotIn('view',sent)
        self.assertNotIn('1',(await self.value())['players'])

    async def test_spawn_click_handles_expiry_with_visible_followup(self):
        self.i.channel_id=5
        self.cog.current_encounter=AsyncMock(side_effect=ValueError('There is no wild Pokémon to catch right now.'))
        await self.cog.open_catch(self.i,message_id=10)
        sent=self.i.followup.send.call_args.kwargs
        self.assertEqual(sent['embed'].title,'Cannot catch')
        self.assertNotIn('view',sent)

    async def test_flee_notice_retries_after_failed_edit_and_survives_new_spawn(self):
        s=state(); s['spawn']={'id':'old','pokemon':pokemon(),'spawned_at':100,
                              'expires':220,'channel':5,'message':10,'attempts':{}}
        await self.value.set(s)
        self.cog.edit_encounter=AsyncMock(return_value=False)
        with patch.object(game.time,'time',return_value=400):
            self.assertTrue(await self.cog.expire_spawn(1,'old'))
        stored=await self.value()
        self.assertIsNone(stored['spawn'])
        self.assertIn('old',stored['pending_spawn_edits'])
        stored['spawn']={'id':'new','pokemon':pokemon(),'spawned_at':500,'expires':800,'message':20}
        await self.value.set(stored)
        self.cog.edit_encounter.return_value=True
        await self.cog.retry_spawn_edits(1)
        stored=await self.value()
        self.assertEqual(stored['pending_spawn_edits'],{})
        self.assertEqual(stored['spawn']['id'],'new')
        self.assertEqual(self.cog.edit_encounter.call_args.args[1]['message'],10)

    async def test_settings_recovers_missing_defaults_and_string_interval(self):
        await self.value.set({'enabled':True,'channel':'5','interval':'300','next_spawn':'1300'})
        await self.cog.admin_route(self.i,'Settings')
        sent=self.i.followup.send.call_args.kwargs
        self.assertIn('Interval: 5 minutes',sent['embed'].description)
        self.assertIn('Next spawn: <t:1300:R>',sent['embed'].description)
        self.assertIn('Scheduler: Running',sent['embed'].description)

    async def test_deferred_settings_edits_original_response_without_followup(self):
        self.i.response.type=5
        self.i.edit_original_response=AsyncMock()
        await self.cog.admin_route(self.i,'Settings')
        self.i.edit_original_response.assert_awaited_once()
        self.i.followup.send.assert_not_awaited()
        kwargs=self.i.edit_original_response.call_args.kwargs
        self.assertNotIn('ephemeral',kwargs)
        self.assertIsInstance(kwargs['view'],game.Menu)

    async def test_scheduler_spawns_when_five_minute_deadline_is_due(self):
        s=state(); s['interval']=300; s['next_spawn']=1300
        await self.value.set(s)
        self.cog.dex.load=AsyncMock()
        self.cog.spawn=AsyncMock()
        with patch.object(game.time,'time',return_value=1299):
            await game.Pokemon.scheduler.fn(self.cog)
        self.cog.spawn.assert_not_awaited()
        with patch.object(game.time,'time',return_value=1300):
            await game.Pokemon.scheduler.fn(self.cog)
        self.cog.spawn.assert_awaited_once_with(1)

    async def test_bad_guild_does_not_stop_scheduler_startup(self):
        self.cog.bot.wait_until_red_ready=AsyncMock()
        self.cog.config.all_guilds=AsyncMock(return_value={1:{},2:{}})
        good=state(); good['spawn']={'id':'s','expires':1300}
        self.cog.state=AsyncMock(side_effect=[ValueError('invalid stored interval'),good])
        self.cog.schedule_expiry=Mock()
        with self.assertLogs('red.pokemon',level='ERROR'):
            await self.cog.before_scheduler()
        self.cog.schedule_expiry.assert_called_once_with(2,good['spawn'])
        self.assertEqual(self.cog.last_errors[1]['source'],'scheduler startup')

    async def test_interaction_error_gets_visible_reference_and_private_trace(self):
        with self.assertLogs('red.pokemon',level='ERROR'):
            await game.View(self.cog).on_error(self.i,TypeError('test error'),None)
        record=self.cog.last_errors[1]
        self.assertIn(record['reference'],self.i.followup.send.call_args.kwargs['embed'].description)
        self.assertIn('TypeError: test error',record['traceback'])

    async def test_active_encounter_red_merge_regression_preserves_all_data(self):
        s=state(); s['next_spawn']=1900
        s['spawn']={'id':'s','pokemon':pokemon(),'spawned_at':100,'expires':220,'message':10}
        rules.account(s,1)['box']['abc']=pokemon()
        s['orders']['receipt']={'user':1,'kind':'shop','status':'complete'}
        self.legacy_value=RedMergeValue(s)
        # This is the exact old read path from the user's traceback.
        with self.assertRaises(TypeError): await self.legacy_value()
        loaded=await self.cog.state(1)
        self.assertEqual(loaded['spawn'],s['spawn'])
        self.assertEqual(loaded['players'],s['players'])
        self.assertEqual(loaded['orders']['receipt']['status'],s['orders']['receipt']['status'])
        self.assertEqual(loaded['orders']['receipt']['guild_id'],1)
        await self.cog.admin_route(self.i,'Settings')
        self.assertEqual(self.i.followup.send.call_args.kwargs['embed'].title,'Pokémon settings')
        # Clear and re-create an encounter, checking both representations read safely.
        loaded['spawn']=None
        await self.cog.save(1,loaded)
        self.assertIsNone((await self.cog.state(1))['spawn'])
        loaded['spawn']=s['spawn']
        await self.cog.save(1,loaded)
        self.assertEqual((await self.cog.state(1))['spawn']['id'],'s')

    async def test_red_merge_regression_scheduler_can_expire_and_spawn_again(self):
        s=state(); s['interval']=300; s['next_spawn']=400
        s['spawn']={'id':'s','pokemon':pokemon(),'spawned_at':100,'expires':220,'message':10}
        self.legacy_value=RedMergeValue(s)
        self.cog.schedule_expiry=Mock()
        self.cog.dex.load=AsyncMock()
        self.cog.spawn=AsyncMock()
        with patch.object(game.time,'time',return_value=400):
            await game.Pokemon.scheduler.fn(self.cog)
        self.assertIsNone((await self.cog.state(1))['spawn'])
        self.cog.spawn.assert_awaited_once_with(1)
        self.assertEqual(self.cog.last_errors,{})

    async def test_pokedex_persists_species_after_transfer_and_deduplicates(self):
        s=state(); player=rules.account(s,1)
        first=pokemon('a'); shiny=pokemon('b'); shiny['shiny']=True
        for mon in (first,shiny):
            player['box'][mon['id']]=mon
            rules.record_catch(player,mon)
        rules.transfer(player,'a',1); rules.transfer(player,'b',1)
        await self.value.set(s)
        view=await self.cog.pokedex_view(1,1)
        self.assertEqual(len(view.entries),1)
        self.assertEqual(view.entries[0][1]['caught'],2)
        self.assertTrue(view.entries[0][1]['shiny'])
        self.assertIn('Bulbasaur',view.render().description)
        self.assertEqual((await self.value())['players']['1']['box'],{})

    async def test_pokedex_backfills_old_box_and_sorts_numerically(self):
        s=state(); player=rules.account(s,1); player.pop('pokedex')
        player['box']={'a':pokemon('a',10),'b':pokemon('b',2),'c':pokemon('c',2)}
        await self.value.set(s)
        view=await self.cog.pokedex_view(1,1)
        self.assertEqual([sid for sid,_ in view.entries],['2','10'])
        self.assertEqual(view.entries[0][1]['caught'],2)
        again=await self.cog.pokedex_view(1,1)
        self.assertEqual(again.entries,view.entries)

    async def test_progress_and_pokestop_cooldown_are_shared_across_servers(self):
        second=await self.cog.state(2);second['enabled']=True;second['channel']=8
        await self.cog.save(2,second)
        with patch.object(game.time,'time',return_value=1000):
            await self.cog.spin_stop(1,1)
            with self.assertRaisesRegex(ValueError,'recharging'): await self.cog.spin_stop(2,1)
        self.assertEqual((await self.cog.state(1))['players'],(await self.cog.state(2))['players'])
        self.assertIs(self.cog.lock(1),self.cog.lock(2))

    async def test_simultaneous_cross_server_spins_cannot_award_twice(self):
        second=await self.cog.state(2);second['enabled']=True;second['channel']=8
        await self.cog.save(2,second)
        with patch.object(game.time,'time',return_value=1000):
            results=await asyncio.gather(self.cog.spin_stop(1,1),self.cog.spin_stop(2,1),return_exceptions=True)
        self.assertEqual(sum(isinstance(r,tuple) for r in results),1)
        self.assertEqual(sum(isinstance(r,ValueError) for r in results),1)

    async def test_nonowner_cannot_change_global_interval_or_global_assets(self):
        self.cog.bot.is_owner.return_value=False
        for action,values in [('Interval',('5',)),('Give Pokémon',('1','1')),('Wipe box',('1',))]:
            with self.assertRaisesRegex(ValueError,'bot owner'): await self.cog.admin_route(self.i,action)
            with self.assertRaisesRegex(ValueError,'bot owner'): await self.cog.admin_action(self.i,action,*values)
        menu=game.Menu(self.cog,1,admin=True,owner_controls=False)
        labels={button.label for button in menu.children}
        self.assertIn('Role bonuses',labels);self.assertIn('Spawn channel',labels)
        self.assertNotIn('Interval',labels);self.assertNotIn('Wipe box',labels)

    async def test_cross_server_catches_share_inventory_without_lost_rewards(self):
        now=time_now()
        first=await self.cog.state(1)
        player=rules.account(first,1);player['items']['master-ball']=2
        first['spawn']={'id':'one','pokemon':pokemon('a'),'spawned_at':now,'expires':now+120,'message':10,'attempts':{}}
        await self.cog.save(1,first)
        second=await self.cog.state(2);second['enabled']=True;second['channel']=8
        second['spawn']={'id':'two','pokemon':pokemon('b'),'spawned_at':now,'expires':now+120,'message':20,'attempts':{}}
        await self.cog.save(2,second)
        other=copy.copy(self.i);other.guild_id=2
        await asyncio.gather(self.cog.catch(self.i,'one','master-ball',None),self.cog.catch(other,'two','master-ball',None))
        player=(await self.cog.state(2))['players']['1']
        self.assertEqual(set(player['box']),{'a','b'})
        self.assertEqual(player['xp'],200);self.assertEqual(player['dust'],200)
        self.assertEqual(player['items']['master-ball'],0)
        self.assertEqual(player['pokedex']['1']['caught'],2)

    async def test_delete_removes_inventory_orders_and_attempts(self):
        s=state(); rules.account(s,1)['box']['abc']=pokemon()
        s['orders']['o']={'user':1,'kind':'shop','status':'complete'}
        s['spawn']={'attempts':{'1':{}},'spawned_at':time_now(),'expires':time_now()+100}; await self.value.set(s)
        await self.cog.red_delete_data_for_user(requester='discord_deleted_user',user_id=1)
        stored=await self.value()
        self.assertNotIn('1',stored['players']); self.assertEqual(stored['orders'],{})
        self.assertEqual(stored['spawn']['attempts'],{})


def time_now():
    import time
    return time.time()


if __name__ == '__main__': unittest.main()
