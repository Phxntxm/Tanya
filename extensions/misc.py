import sys
from datetime import datetime

import discord
from discord.ext import commands


class Miscellaneous(commands.Cog):
    @commands.command()
    async def help(self, ctx):
        """Provides useful information for using this bot"""
        embed = discord.Embed(
            title="Information",
            description="Welcome to Tanya Degurechaff, a customizable bot for Mafia type games. "
            "This bot emulates the mafia style game, similar to Town of Salem but *does* take some liberties to change some things."
            "\n\nIn order to start a game, simply use `>>mafia start`. If you want to see some information on the roles available, "
            "run `>>mafia roles`. If you want to see information on a specific role run `>>mafia role Doctor` for example.",
            color=0xFF0000,
            timestamp=datetime.utcnow(),
        )
        embed.set_author(
            name="Dev Server",
            url="https://discord.gg/B6qJ4NKGvp",
            icon_url=ctx.bot.user.avatar_url,
        )
        await ctx.send(embed=embed)

    @commands.command(aliases=["invite"])
    async def addbot(self, ctx):
        """Provides a link that you can use to add me to a server"""
        perms = discord.Permissions.none()
        perms.send_messages = True
        perms.read_messages = True
        perms.manage_roles = True
        perms.manage_channels = True
        perms.manage_messages = True
        perms.mention_everyone = True
        app_info = await ctx.bot.application_info()
        await ctx.send(
            "Use this URL to add me to a server that you'd like!\n<{}>".format(
                discord.utils.oauth_url(app_info.id, perms)
            )
        )

    @commands.command(aliases=["guild"])
    async def server(self, ctx):
        """Provides an invite link to the official server"""
        await ctx.send("https://discord.gg/B6qJ4NKGvp")

    @commands.command()
    async def prefix(self, ctx):
        """Sends the bot prefix"""
        await ctx.send("My prefix is >>")

    @commands.command(aliases="botinfo")
    async def info(self, ctx):
        """Sends some information about this bot"""
        description = f"""
Python version: {sys.version_info.major}.{sys.version_info.minor}{sys.version_info.micro}
Discord version: {discord.__version__}
Games playing: {len(ctx.bot.get_cog("Mafia").games)}
Custom roles implemented: {len(ctx.bot.__special_roles__)}
"""
        embed = discord.Embed(
            title=ctx.bot.user.name,
            description=description,
            color=0xFF0000,
            timestamp=datetime.utcnow(),
        )
        embed.set_author(
            name="Dev Server",
            url="https://discord.gg/B6qJ4NKGvp",
            icon_url=ctx.bot.user.avatar_url,
        )
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Miscellaneous())
