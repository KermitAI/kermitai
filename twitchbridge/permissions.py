"""Discord access tiers shared by command checks and internal dispatch."""
from redbot.core import commands


async def discord_access(bot, guild, author, *, moderators=True):
    if await bot.is_owner(author):
        return True
    if guild is None:
        return False
    if author.id == guild.owner_id:
        return True
    if getattr(author.guild_permissions, "administrator", False):
        return True
    is_admin = getattr(bot, "is_admin", None)
    if is_admin is not None and await is_admin(author):
        return True
    return bool(moderators and await bot.is_mod(author))


def staff_only():
    async def predicate(ctx):
        return await discord_access(ctx.bot, ctx.guild, ctx.author)
    return commands.check(predicate)


def admin_only():
    async def predicate(ctx):
        return await discord_access(ctx.bot, ctx.guild, ctx.author, moderators=False)
    return commands.check(predicate)
