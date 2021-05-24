import asyncio
import inspect
import io
import re
import textwrap
import traceback
from contextlib import redirect_stdout

import discord
from discord.ext import commands


def get_syntax_error(e):
    if e.text is None:
        return "```py\n{0.__class__.__name__}: {0}\n```".format(e)
    return "```py\n{0.text}{1:>{0.offset}}\n{2}: {0}```".format(e, "^", type(e).__name__)


class Owner(commands.Cog, command_attrs={"hidden": True}):
    """Commands that can only be used by the owner of the bot, bot management commands"""

    _last_result = None
    sessions = set()

    async def cog_check(self, ctx):
        return await ctx.bot.is_owner(ctx.author)

    @staticmethod
    def cleanup_code(content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith("```") and content.endswith("```"):
            return "\n".join(content.split("\n")[1:-1])

        # remove `foo`
        return content.strip("` \n")

    @commands.command()
    async def repl(self, ctx):
        msg = ctx.message

        variables = {
            "ctx": ctx,
            "bot": ctx.bot,
            "message": msg,
            "guild": msg.guild,
            "server": msg.guild,
            "channel": msg.channel,
            "author": msg.author,
            "self": self,
            "_": None,
        }

        if msg.channel.id in self.sessions:
            await ctx.send("Already running a REPL session in this channel. Exit it with `quit`.")
            return

        self.sessions.add(msg.channel.id)
        await ctx.send("Enter code to execute or evaluate. `exit()` or `quit` to exit.")

        def check(m):
            return m.author.id == msg.author.id and m.channel.id == msg.channel.id and m.content.startswith("`")

        code = None

        while True:
            try:
                response = await ctx.bot.wait_for("message", check=check, timeout=10.0 * 60.0)
            except asyncio.TimeoutError:
                await ctx.send("Exiting REPL session.")
                self.sessions.remove(msg.channel.id)
                break

            cleaned = self.cleanup_code(response.content)

            if cleaned in ("quit", "exit", "exit()"):
                await ctx.send("Exiting.")
                self.sessions.remove(msg.channel.id)
                return

            executor = exec
            if cleaned.count("\n") == 0:
                # single statement, potentially 'eval'
                try:
                    code = compile(cleaned, "<repl session>", "eval")
                except SyntaxError:
                    pass
                else:
                    executor = eval

            if executor is exec:
                try:
                    code = compile(cleaned, "<repl session>", "exec")
                except SyntaxError as e:
                    await ctx.send(get_syntax_error(e))
                    continue

            variables["message"] = response

            fmt = None
            stdout = io.StringIO()

            try:
                with redirect_stdout(stdout):
                    result = executor(code, variables)
                    if inspect.isawaitable(result):
                        result = await result
            except Exception:
                value = stdout.getvalue()
                fmt = "```py\n{}{}\n```".format(value, traceback.format_exc())
            else:
                value = stdout.getvalue()
                if result is not None:
                    fmt = "```py\n{}{}\n```".format(value, result)
                    variables["_"] = result
                elif value:
                    fmt = "```py\n{}\n```".format(value)

            try:
                if fmt is not None:
                    if len(fmt) > 2000:
                        await ctx.send("Content too big to be printed.")
                    else:
                        await ctx.send(fmt)
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                await ctx.send("Unexpected error: `{}`".format(e))

    @commands.command()
    async def sendtochannel(self, ctx, cid: int, *, message):
        """Sends a message to a provided channel, by ID"""
        channel = ctx.bot.get_channel(cid)
        await channel.send(message)
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

    @commands.command()
    async def debug(self, ctx, *, body: str):
        env = {
            "bot": ctx.bot,
            "ctx": ctx,
            "channel": ctx.message.channel,
            "author": ctx.message.author,
            "server": ctx.message.guild,
            "guild": ctx.message.guild,
            "message": ctx.message,
            "self": self,
            "_": self._last_result,
        }

        env.update(globals())

        body = self.cleanup_code(body)
        stdout = io.StringIO()

        to_compile = "async def func():\n%s" % textwrap.indent(body, "  ")

        try:
            exec(to_compile, env)
        except SyntaxError as e:
            return await ctx.send(get_syntax_error(e))

        func = env["func"]
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception:
            value = stdout.getvalue()
            await ctx.send(f"```py\n{value}{traceback.format_exc()}\n```"[:2000])
        else:
            value = stdout.getvalue()
            try:
                await ctx.message.add_reaction("\u2705")
            except Exception:
                pass

            if ret is None:
                if value:
                    await ctx.send(f"```py\n{value}\n```"[:2000])
            else:
                self._last_result = ret
                await ctx.send(f"```py\n{value}{ret}\n```"[:2000])

    @commands.command()
    async def bash(self, ctx, *, cmd: str):
        """Runs a bash command"""
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        m = r"(https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
        stdout = (await proc.communicate())[0]
        if stdout:
            output = re.sub(m, r"<\1>", stdout.decode())
            await ctx.send(f"[stdout]\n{output}")
        else:
            await ctx.send("Process finished, no output")

    @commands.command()
    async def shutdown(self, ctx):
        """Shuts the bot down"""
        fmt = "Shutting down, I will miss you {0.author.name}"
        await ctx.send(fmt.format(ctx.message))
        await ctx.bot.logout()
        await ctx.bot.close()

    @commands.command()
    async def name(self, ctx, new_nick: str):
        """Changes the bot's name"""
        await ctx.bot.user.edit(username=new_nick)
        await ctx.send("Changed username to " + new_nick)

    @commands.command()
    async def status(self, ctx, *, status: str):
        """Changes the bot's 'playing' status"""
        await ctx.bot.change_presence(activity=discord.Game(name=status, type=0))
        await ctx.send("Just changed my status to '{}'!".format(status))

    @commands.command()
    async def load(self, ctx, *modules: str):
        """Loads a module"""

        for ext in modules:
            # Do this because I'm too lazy to type extensions.module
            ext = ext.lower()
            if not ext.startswith("extensions"):
                ext = "extensions.{}".format(ext)

            ctx.bot.load_extension(ext)
        await ctx.send(f"I have just loaded the module(s): {', '.join(modules)}")

    @commands.command()
    async def unload(self, ctx, *modules: str):
        """Unloads a module"""

        for ext in modules:
            # Do this because I'm too lazy to type extensions.module
            ext = ext.lower()
            if not ext.startswith("extensions"):
                ext = "extensions.{}".format(ext)

            ctx.bot.unload_extension(ext)
        await ctx.send(f"I have just unloaded the module(s): {', '.join(modules)}")

    @commands.command()
    async def reload(self, ctx, *modules: str):
        """Reloads a module"""

        for ext in modules:
            # Do this because I'm too lazy to type extensions.module
            ext = ext.lower()
            if not ext.startswith("extensions"):
                ext = "extensions.{}".format(ext)

            ctx.bot.reload_extension(ext)
        await ctx.send(f"I have just reloaded the module(s): {', '.join(modules)}")


def setup(bot):
    bot.add_cog(Owner(bot))
