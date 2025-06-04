import discord
import asyncio
import feedparser
from redbot.core import commands, Config

class fivebells(commands.Cog):
    """Automatically posts RSS updates to different channels"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_guild = {
            "rss_feeds": {},  # Stores RSS URLs mapped to Discord channels
            "embed_color": discord.Color.red().value,
            "role_tag": None,
            "interval": 60,
            "last_posted_titles": {},  # Track last posted titles per feed
        }
        self.config.register_guild(**default_guild)
        self.bot.loop.create_task(self.auto_post_task())

    async def auto_post_task(self):
        """Background task to fetch and post RSS updates"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    rss_feeds = await self.config.guild(guild).rss_feeds()
                    last_posted_titles = await self.config.guild(guild).last_posted_titles()

                    for rss_url, channel_id in rss_feeds.items():
                        channel = guild.get_channel(channel_id)
                        if not channel:
                            continue

                        feed = feedparser.parse(rss_url)
                        if not feed.entries:
                            continue

                        entry = feed.entries[0]
                        last_posted = last_posted_titles.get(rss_url, None)

                        if entry.title == last_posted:
                            continue  # Avoid duplicate posting

                        embed = discord.Embed(
                            title=entry.title,
                            url=entry.link,
                            description=entry.summary,
                            color=await self.config.guild(guild).embed_color()
                        )
                        # Try to set thumbnail from entry.media_thumbnail or entry.media_content or entry.image
                        thumbnail_url = None
                        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                            thumbnail_url = entry.media_thumbnail[0].get("url")
                        elif hasattr(entry, "media_content") and entry.media_content:
                            thumbnail_url = entry.media_content[0].get("url")
                        elif hasattr(entry, "image") and entry.image:
                            # Some feeds use entry.image.href or entry.image.url
                            thumbnail_url = getattr(entry.image, "href", None) or getattr(entry.image, "url", None)
                        if thumbnail_url:
                            embed.set_thumbnail(url=thumbnail_url)
                        embed.set_footer(text="Latest Update")
                        role = await self.config.guild(guild).role_tag()
                        message = f"{role}" if role else ""

                        await channel.send(message, embed=embed)
                        last_posted_titles[rss_url] = entry.title

                    await self.config.guild(guild).last_posted_titles.set(last_posted_titles)

                interval = await self.config.guild(guild).interval()
                await asyncio.sleep(interval * 60)

            except Exception as e:
                print(f"Error in auto_post_task: {e}")

    @commands.group()
    async def fivebells(self, ctx):
        """Base command for managing the FiveBells cog"""
        if ctx.invoked_subcommand is None:
            await ctx.send("Commands as follows:")

    @fivebells.command()
    async def addfeed(self, ctx, rss_url: str, channel: discord.TextChannel):
        """Adds an RSS feed and assigns it to a Discord channel"""
        rss_feeds = await self.config.guild(ctx.guild).rss_feeds()
        if rss_url in rss_feeds:
            await ctx.send("This RSS feed is already assigned to a channel.")
            return
        
        rss_feeds[rss_url] = channel.id
        await self.config.guild(ctx.guild).rss_feeds.set(rss_feeds)
        await ctx.send(f"RSS feed `{rss_url}` added for `{channel.mention}`.")

    @fivebells.command()
    async def removefeed(self, ctx, rss_url: str):
        """Removes an RSS feed"""
        rss_feeds = await self.config.guild(ctx.guild).rss_feeds()
        if rss_url not in rss_feeds:
            await ctx.send("This RSS feed is not currently being tracked.")
            return
        
        del rss_feeds[rss_url]
        await self.config.guild(ctx.guild).rss_feeds.set(rss_feeds)
        await ctx.send(f"RSS feed `{rss_url}` removed.")

    @fivebells.command()
    async def listfeeds(self, ctx):
        """Lists all stored RSS feeds and their assigned channels"""
        rss_feeds = await self.config.guild(ctx.guild).rss_feeds()
        if not rss_feeds:
            await ctx.send("No RSS feeds are currently stored.")
            return

        feed_list = "\n".join([f"`{url}` → <#{channel_id}>" for url, channel_id in rss_feeds.items()])
        await ctx.send(f"Tracked RSS feeds:\n{feed_list}")

    @fivebells.command()
    async def setinterval(self, ctx, minutes: int):
        """Sets how often the bot fetches new RSS updates"""
        if minutes < 5:
            await ctx.send("Interval must be at least 5 minutes.")
            return
        
        await self.config.guild(ctx.guild).interval.set(minutes)
        await ctx.send(f"Automatic updates set to every {minutes} minutes.")

    @fivebells.command()
    async def setcolor(self, ctx, color: discord.Color):
        """Sets the embed color for posts"""
        await self.config.guild(ctx.guild).embed_color.set(color.value)
        await ctx.send(f"Embed color updated.")

    @fivebells.command()
    async def setrole(self, ctx, role: discord.Role):
        """Sets a role to tag when posting RSS updates"""
        await self.config.guild(ctx.guild).role_tag.set(role.mention)
        await ctx.send(f"Role tag set to {role.mention}")
    
    @fivebells.command()
    async def forcepost(self, ctx, rss_url: str):
        """Forces a post from the specified RSS feed"""
        rss_feeds = await self.config.guild(ctx.guild).rss_feeds()
        if rss_url not in rss_feeds:
            await ctx.send("This RSS feed is not currently being tracked.")
            return
        
        channel_id = rss_feeds[rss_url]
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            await ctx.send("The channel for this RSS feed no longer exists.")
            return
        
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            await ctx.send("No new entries found in the RSS feed.")
            return
        
        entry = feed.entries[0]
        embed = discord.Embed(
            title=entry.title,
            url=entry.link,
            description=entry.summary,
            color=await self.config.guild(ctx.guild).embed_color()
        )
        
        thumbnail_url = None
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            thumbnail_url = entry.media_thumbnail[0].get("url")
        elif hasattr(entry, "media_content") and entry.media_content:
            thumbnail_url = entry.media_content[0].get("url")
        elif hasattr(entry, "image") and entry.image:
            thumbnail_url = getattr(entry.image, "href", None) or getattr(entry.image, "url", None)
        
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        
        embed.set_footer(text="Latest Update")
        role = await self.config.guild(ctx.guild).role_tag()
        message = f"{role}" if role else ""
        
        await channel.send(message, embed=embed)
        last_posted_titles = await self.config.guild(ctx.guild).last_posted_titles()
        last_posted_titles[rss_url] = entry.title
        await self.config.guild(ctx.guild).last_posted_titles.set(last_posted_titles)
        
        await ctx.send(f"Forced post from `{rss_url}` to {channel.mention}.")

def setup(bot):
    bot.add_cog(fivebells(bot))
