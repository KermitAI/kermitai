import discord
from redbot.core import commands, Config
from redbot.core.utils import schedules
import feedparser

RSS_URL = "https://www.iaff.org/feed/lodd"

class fivebells(commands.Cog):
    """Automatically posts LODD reports for fallen firefighters and EMS personnel"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_guild = {
            "rss_url": RSS_URL,
            "embed_color": discord.Color.red().value,
            "role_tag": None,
            "interval": 60,
            "last_posted_title": None,
            "post_channel": None
        }
        self.config.register_guild(**default_guild)
        self.auto_post.start()  

    def cog_unload(self):
        """Stops the background task when the cog is unloaded"""
        self.auto_post.cancel()

    @tasks.loop(minutes=60)
    async def auto_post(self):
        """Automatically posts new LODD reports in the designated channel"""
        for guild in self.bot.guilds:
            channel_id = await self.config.guild(guild).post_channel()
            channel = guild.get_channel(channel_id)
            if not channel:
                continue  # Skip if no valid channel is set
            
            feed = feedparser.parse(await self.config.guild(guild).rss_url())
            if not feed.entries:
                continue

            entry = feed.entries[0]
            last_posted = await self.config.guild(guild).last_posted_title()
            
            if entry.title == last_posted:
                continue  # Prevent duplicate posts
            
            embed = discord.Embed(title=entry.title, url=entry.link, description=entry.summary, color=await self.config.guild(guild).embed_color())
            embed.set_footer(text="Honoring the fallen.")
            role = await self.config.guild(guild).role_tag()
            message = f"{role} New Line of Duty Death Report:" if role else "New Line of Duty Death Report:"
            
            await channel.send(message, embed=embed)
            await self.config.guild(guild).last_posted_title.set(entry.title)

    @commands.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Sets the channel for automatic postings"""
        await self.config.guild(ctx.guild).post_channel.set(channel.id)
        await ctx.send(f"LODD reports will now be posted in {channel.mention}.")

    @commands.command()
    async def getlastlodd(self, ctx):
        """Fetches and posts the most recent LODD report"""
        feed = feedparser.parse(await self.config.guild(ctx.guild).rss_url())
        if not feed.entries:
            await ctx.send("No new LODD reports found.")
            return

        entry = feed.entries[0]
        embed = discord.Embed(title=entry.title, url=entry.link, description=entry.summary, color=await self.config.guild(ctx.guild).embed_color())
        embed.set_footer(text="Honoring the fallen.")
        role = await self.config.guild(ctx.guild).role_tag()
        message = f"{role} Latest Line of Duty Death Report:" if role else "Latest Line of Duty Death Report:"
        
        await ctx.send(message, embed=embed)
        await self.config.guild(ctx.guild).last_posted_title.set(entry.title)

def setup(bot):
    bot.add_cog(fivebells(bot))
