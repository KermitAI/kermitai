import discord
import asyncio
import feedparser
from redbot.core import commands, Config

RSS_URL = "https://www.iaff.org/feed/lodd"

class fivebells(commands.Cog):
    """Automatically posts LODD reports for fallen firefighters & EMS personnel"""

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
        self.bot.loop.create_task(self.auto_post_task())  # Start background posting task

    async def auto_post_task(self):
        """Background task to fetch and post new LODD reports"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    channel_id = await self.config.guild(guild).post_channel()
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        continue

                    feed = feedparser.parse(await self.config.guild(guild).rss_url())
                    if not feed.entries:
                        continue

                    entry = feed.entries[0]
                    last_posted = await self.config.guild(guild).last_posted_title()

                    if entry.title == last_posted:
                        continue  # Avoid duplicate posting

                    embed = discord.Embed(title=entry.title, url=entry.link, description=entry.summary, color=await self.config.guild(guild).embed_color())
                    embed.set_footer(text="Honoring the fallen.")
                    role = await self.config.guild(guild).role_tag()
                    message = f"{role} New Line of Duty Death Report:" if role else "New Line of Duty Death Report:"

                    await channel.send(message, embed=embed)
                    await self.config.guild(guild).last_posted_title.set(entry.title)

                interval = await self.config.guild(guild).interval()
                await asyncio.sleep(interval * 60)  # Convert minutes to seconds

            except Exception as e:
                print(f"Error in auto_post_task: {e}")

    @commands.group()
    async def fivebells(self, ctx):
        """Base command for managing the FiveBells cog"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Available subcommands: `setchannel`, `setinterval`, `getlastpost`, `setcolor`, `setrole`.")

    @fivebells.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Sets the channel for automatic postings"""
        await self.config.guild(ctx.guild).post_channel.set(channel.id)
        await ctx.send(f"LODD reports will now be posted in {channel.mention}.")

    @fivebells.command()
    async def setinterval(self, ctx, minutes: int):
        """Sets how often the bot fetches new LODD reports"""
        if minutes < 5:
            await ctx.send("Interval must be at least 5 minutes.")
            return
        
        await self.config.guild(ctx.guild).interval.set(minutes)
        await ctx.send(f"Automatic updates set to every {minutes} minutes.")

    @fivebells.command()
    async def getlastpost(self, ctx):
        """Manually fetches and posts the most recent LODD report"""
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

    @fivebells.command()
    async def setcolor(self, ctx, color: discord.Color):
        """Sets the embed color for posts"""
        await self.config.guild(ctx.guild).embed_color.set(color.value)
        await ctx.send(f"Embed color updated.")

    @fivebells.command()
    async def setrole(self, ctx, role: discord.Role):
        """Sets a role to tag when posting LODD reports"""
        await self.config.guild(ctx.guild).role_tag.set(role.mention)
        await ctx.send(f"Role tag set to {role.mention}")

def setup(bot):
    bot.add_cog(fivebells(bot))
