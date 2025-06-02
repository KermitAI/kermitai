import discord
from redbot.core import commands, Config
import feedparser

RSS_URL = "https://www.iaff.org/feed/lodd"  # Replace with correct feed URL

class fivebells(commands.Cog):  # Changed to lowercase
    """Posts LODD reports for fallen firefighters and EMS personnel"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_guild = {"rss_url": RSS_URL, "embed_color": discord.Color.red().value, "role_tag": None}
        self.config.register_guild(**default_guild)

    @commands.command()
    async def lodd(self, ctx):
        """Fetches and posts the latest LODD report"""
        feed = feedparser.parse(await self.config.guild(ctx.guild).rss_url())
        if not feed.entries:
            await ctx.send("No new LODD reports found.")
            return
        
        entry = feed.entries[0]
        embed = discord.Embed(title=entry.title, url=entry.link, description=entry.summary, color=await self.config.guild(ctx.guild).embed_color())
        embed.set_footer(text="Honoring the fallen.")
        
        role = await self.config.guild(ctx.guild).role_tag()
        message = f"{role} New Line of Duty Death Report:" if role else "New Line of Duty Death Report:"
        await ctx.send(message, embed=embed)

    @commands.command()
    async def setrole(self, ctx, role: discord.Role):
        """Sets a role to tag when posting LODD reports"""
        await self.config.guild(ctx.guild).role_tag.set(role.mention)
        await ctx.send(f"Role tag set to {role.mention}")

    @commands.command()
    async def setcolor(self, ctx, color: discord.Color):
        """Sets the embed color"""
        await self.config.guild(ctx.guild).embed_color.set(color.value)
        await ctx.send(f"Embed color updated.")

def setup(bot):
    bot.add_cog(fivebells(bot))  # Changed to lowercase
