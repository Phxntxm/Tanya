import discord
from discord.ext import commands


class Miscellaneous(commands.Cog):
    @commands.command(aliases=["invite"])
    async def addbot(self, ctx):
        """Provides a link that you can use to add me to a server"""
        perms = discord.Permissions.none()
        perms.send_messages = True
        perms.read_messages = True
        perms.manage_roles = True
        perms.manage_channels = True
        perms.manage_messages = True
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


def setup(bot):
    bot.add_cog(Miscellaneous())
