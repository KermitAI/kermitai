import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from test_policy import policy

# Exercise the real listener without requiring a running Red or Discord instance.
source = ast.parse((Path(__file__).resolve().parents[1] / "verifykick.py").read_text(encoding="utf-8"))
node = next(n for n in next(n for n in source.body if isinstance(n, ast.ClassDef)).body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_message")
node.decorator_list = []
class HTTPException(Exception):
    pass
class NotFound(HTTPException):
    pass
namespace = {"discord": NS(NotFound=NotFound, HTTPException=HTTPException),
             "can_instant_kick": policy.can_instant_kick, "log": logging.getLogger("test")}
exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "listener", "exec"), namespace)


class ListenerTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = {"instant_channel_id": 10, "instant_role_ids": [99], "channel_id": None}
        self.me = NS(id=123, top_role=10, guild_permissions=NS(kick_members=True))
        self.guild = NS(id=1, owner_id=1, me=self.me, get_role=lambda rid: NS(id=rid),
                        fetch_member=AsyncMock())
        self.member = NS(id=2, guild=self.guild, roles=[], top_role=2,
                         guild_permissions=NS(administrator=False), kick=AsyncMock())
        self.guild.fetch_member.return_value = self.member
        self.bot = NS(user=self.me, cog_disabled_in_guild=AsyncMock(return_value=False))
        self.cog = NS(bot=self.bot, config=NS(guild=lambda g: NS(all=AsyncMock(return_value=self.settings))),
                      _instant_lock=lambda g: asyncio.Lock())
        self.message = NS(guild=self.guild, channel=NS(id=10), webhook_id=None, author=NS(id=2))

    async def run_listener(self):
        await namespace["on_message"](self.cog, self.message)

    async def test_kicks_immediately(self):
        await self.run_listener()
        self.member.kick.assert_awaited_once()

    async def test_refreshed_role_exempts(self):
        self.member.roles = [NS(id=99)]
        await self.run_listener()
        self.member.kick.assert_not_awaited()

    async def test_wrong_or_disabled_channel(self):
        for channel in (11, None):
            self.settings["instant_channel_id"] = channel
            await self.run_listener()
        self.guild.fetch_member.assert_not_awaited()

    async def test_deleted_role_or_disabled_cog(self):
        self.guild.get_role = lambda rid: None
        await self.run_listener()
        self.guild.get_role = lambda rid: NS(id=rid)
        self.bot.cog_disabled_in_guild.return_value = True
        await self.run_listener()
        self.member.kick.assert_not_awaited()

    async def test_webhook_or_dm(self):
        self.message.webhook_id = 7
        await self.run_listener()
        self.message.webhook_id = None
        self.message.guild = None
        await self.run_listener()
        self.guild.fetch_member.assert_not_awaited()

    async def test_departed_member(self):
        self.guild.fetch_member.side_effect = NotFound()
        await self.run_listener()
        self.member.kick.assert_not_awaited()
