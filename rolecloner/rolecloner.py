from redbot.core import commands
import discord

class rolecloner(commands.Cog):
    """Cog to clone a role"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def clone_role(self, ctx, role: discord.Role):
        """Clone a role, including its permissions, name, and color"""
        try:
            new_role = await ctx.guild.create_role(
                name=role.name,
                permissions=role.permissions,
                colour=role.colour,
                hoist=role.hoist,
                mentionable=role.mentionable
            )
            await ctx.send(f"Role '{role.name}' cloned successfully!")
        except Exception as e:
            await ctx.send(f"Failed to clone role: {e}")

def setup(bot):
    bot.add_cog(rolecloner(bot))