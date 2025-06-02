import discord
from redbot.core import commands, Config, tasks
import feedparser

RSS_URL = "https://www.iaff.org/feed/lodd"  # Replace with correct feed URL

class fivebells(commands.Cog):
    """Posts LODD reports for fallen firefighters and EMS personnel automatically"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_guild = {"rss_url": RSS_URL, "embed_color": discord.Color.red().value, "role_tag": None, "interval": 60, "last_posted_title": None}
        self.config.register_guild(**default_guild)
        self.auto_post.start()  # Start background task

    def cog_unload(self):
        """Stop the background task when the cog is unloaded"""
        self.auto_post.cancel()

    @tasks.loop(minutes=60)
    async def auto_post(self):
        """Automatically fetches and posts new LODD reports"""
        for guild in self.bot.guilds:
            channel = guild.system_channel  # Replace with preferred channel logic
            if not channel:
                continue
            
            feed = feedparser.parse(await self.config.guild(guild).rss_url())
            if not feed.entries:
                continue

            entry = feed.entries[0]
            last_posted = await self.config.guild(guild).last_posted_title()
            
            if entry.title == last_posted:  # Prevent duplicate posting
                continue
            
            embed = discord.Embed(title=entry.title, url=entry.link, description=entry.summary, color=await self.config.guild(guild).embed_color())
            embed.set_footer(text="Honoring the fallen.")
            role = await self.config.guild(guild).role_tag()
            message = f"{role} New Line of Duty Death Report:" if role else "New Line of Duty Death Report:"
            
            await channel.send(message, embed=embed)
            await self.config.guild(guild).last_posted_title.set(entry.title)

    @commands.command()
    async def setinterval(self, ctx, minutes: int):
        """Sets the automatic update interval"""
        if minutes < 5:
            await ctx.send("Interval must be at least 5 minutes.")
            return
        
        await self.config.guild(ctx.guild).interval.set(minutes)
        self.auto_post.change_interval(minutes=minutes)
        await ctx.send(f"Automatic updates set to every {minutes} minutes.")

    @commands.command()
    async def lodd(self, ctx):
        """Manually fetches and posts the latest LODD report"""
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
        await self.config.guild(ctx.guild).last_posted_title.set(entry.title)

def setup(bot):
    bot.add_cog(fivebells(bot))
