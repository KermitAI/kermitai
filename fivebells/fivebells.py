import discord
import asyncio
import feedparser
from bs4 import BeautifulSoup
from redbot.core import commands, Config
import re

class fivebells(commands.Cog):
    """Automatically posts RSS updates to different channels"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_guild = {
            "rss_feeds": {},
            "embed_color": discord.Color.red().value,
            "role_tag": None,
            "interval": 60,
            "last_posted_titles": {},
        }
        self.config.register_guild(**default_guild)
        self.bot.loop.create_task(self.auto_post_task())

    async def auto_post_task(self):
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
                            continue

                        raw_content = self.extract_raw_content(entry)
                        description = self.clean_description(raw_content)
                        description = self.bold_officer_name(description)
                        thumbnail_url = self.extract_first_image_url(raw_content)

                        embed = discord.Embed(
                            title=entry.title,
                            url=entry.link,
                            description=description[:2048],
                            color=await self.config.guild(guild).embed_color()
                        )

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

    def extract_raw_content(self, entry):
        if "content" in entry and isinstance(entry["content"], list) and "value" in entry["content"][0]:
            return entry["content"][0]["value"]
        return entry.get("summary", "No description available.")

    def clean_description(self, html):
        return BeautifulSoup(html, "html.parser").get_text()

    def extract_first_image_url(self, html):
        soup = BeautifulSoup(html, "html.parser")
        img_tag = soup.find("img")
        if img_tag and img_tag.has_attr("src"):
            return img_tag["src"]
        return None

    def bold_officer_name(self, text):
        match = re.search(r"Officer ([A-Z][a-z]+(?: [A-Z][a-z]+)?)", text)
        if match:
            name = match.group(1)
            return text.replace(f"Officer {name}", f"**Officer {name}**")
        return text

    @commands.group(aliases=["fb", "bells"])
    async def fivebells(self, ctx):
        if ctx.invoked_subcommand is None:
            cmds = [
                ("addfeed", "Adds an RSS feed and assigns it to a Discord channel."),
                ("removefeed", "Removes a tracked RSS feed."),
                ("listfeeds", "Lists all stored RSS feeds and their assigned channels."),
                ("setinterval", "Sets how often the bot fetches new RSS updates (in minutes)."),
                ("setcolor", "Sets the embed color for posts."),
                ("setrole", "Sets a role to tag when posting RSS updates."),
                ("forcepost", "Forces a post from the specified RSS feed immediately.")
            ]
            msg = "Available commands:\n" + "\n".join([f"**{name}** - {desc}" for name, desc in cmds])
            await ctx.send(msg)

    @fivebells.command()
    async def addfeed(self, ctx, rss_url: str, channel: discord.TextChannel):
        """Adds an RSS feed and assigns it to a Discord channel."""
        rss_feeds = await self.config.guild(ctx.guild).rss_feeds()
        if rss_url in rss_feeds:
            await ctx.send("This RSS feed is already assigned to a channel.")
            return

        rss_feeds[rss_url] = channel.id
        await self.config.guild(ctx.guild).rss_feeds.set(rss_feeds)
        await ctx.send(f"RSS feed `{rss_url}` added for `{channel.mention}`.")

    @fivebells.command()
    async def removefeed(self, ctx, index: int):
        """Removes a tracked RSS feed by its index."""
        rss_feeds = await self.config.guild(ctx.guild).rss_feeds()
        rss_list = list(rss_feeds.items())
        if index < 1 or index > len(rss_list):
            await ctx.send("Invalid index.")
            return

        rss_url, _ = rss_list[index - 1]
        del rss_feeds[rss_url]
        await self.config.guild(ctx.guild).rss_feeds.set(rss_feeds)
        await ctx.send(f"RSS feed `{rss_url}` removed.")

    @fivebells.command()
    async def listfeeds(self, ctx):
        """Lists all stored RSS feeds and their assigned channels."""
        rss_feeds = await self.config.guild(ctx.guild).rss_feeds()
        if not rss_feeds:
            await ctx.send("No RSS feeds are currently stored.")
            return

        feed_list = "\n".join([f"**{i+1}.** `{url}` → <#{channel_id}>" for i, (url, channel_id) in enumerate(rss_feeds.items())])
        await ctx.send(f"Tracked RSS feeds:\n{feed_list}")

    @fivebells.command()
    async def setinterval(self, ctx, minutes: int):
        """Sets how often the bot fetches new RSS updates (in minutes)."""
        if minutes < 5:
            await ctx.send("Interval must be at least 5 minutes.")
            return

        await self.config.guild(ctx.guild).interval.set(minutes)
        await ctx.send(f"Automatic updates set to every {minutes} minutes.")

    @fivebells.command()
    async def setcolor(self, ctx, color: discord.Color):
        """Sets the embed color for posts."""
        await self.config.guild(ctx.guild).embed_color.set(color.value)
        await ctx.send(f"Embed color updated.")

    @fivebells.command()
    async def setrole(self, ctx, role: discord.Role):
        """Sets a role to tag when posting RSS updates."""
        await self.config.guild(ctx.guild).role_tag.set(role.mention)
        await ctx.send(f"Role tag set to {role.mention}")

    @fivebells.command()
    async def forcepost(self, ctx, index: int):
        """Forces a post from the specified RSS feed by index."""
        rss_feeds = await self.config.guild(ctx.guild).rss_feeds()
        rss_list = list(rss_feeds.items())
        if index < 1 or index > len(rss_list):
            await ctx.send("Invalid index.")
            return

        rss_url, channel_id = rss_list[index - 1]
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            await ctx.send("The channel for this RSS feed no longer exists.")
            return

        feed = feedparser.parse(rss_url)
        if not feed.entries:
            await ctx.send("No new entries found in the RSS feed.")
            return

        entry = feed.entries[0]
        raw_content = self.extract_raw_content(entry)
        description = self.clean_description(raw_content)
        description = self.bold_officer_name(description)
        thumbnail_url = self.extract_first_image_url(raw_content)

        embed = discord.Embed(
            title=entry.title,
            url=entry.link,
            description=description[:2048],
            color=await self.config.guild(ctx.guild).embed_color()
        )

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