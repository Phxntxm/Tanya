import collections
import typing

import asyncpg
import discord
from discord.ext import commands
from utils import Context

if typing.TYPE_CHECKING:
    from utils.custom_bot import MafiaBot


def condition(predicate: typing.Callable[[asyncpg.Record], bool], data: list) -> int:
    return len(tuple(filter(predicate, data)))


class Stats(commands.Cog):
    @commands.command("stats")
    async def stats(
        self,
        ctx: Context,
        user: typing.Optional[discord.User] = None,
        only_this_server=False,
    ):
        """
        Fetches stats for yourself, or for a specific user.
        You can put 'yes' after the user to fetch stats for only this server
        """
        user = user or ctx.author

        if only_this_server and not ctx.guild:
            return await ctx.reply(
                "You cannot get server stats in dms", mention_author=False
            )

        query = """
        SELECT
            games.id, guild_id, day_count, p.win, p.die, r.name AS role, r.alignment
        FROM games
        INNER JOIN players p ON 
            games.id = p.game_id AND p.user_id = $1
        INNER JOIN roles r ON
            r.id = p.role
        WHERE
            user_id = $1
        """
        async with ctx.acquire() as conn:
            games = await conn.fetch(query, user.id)

            query = """
            SELECT
                game_id, killer, killed, night, suicide
            FROM kills
            WHERE
                killer = $1 OR killed = $1
            """
            kills = await conn.fetch(query, user.id)

        if not games:
            return await ctx.reply(f"No stats for {user}", mention_author=False)

        if only_this_server:
            games = list(filter(lambda row: row["guild_id"] == ctx.guild.id, games))
            _game_ids = tuple(x["id"] for x in games)
            kills = list(filter(lambda row: row["game_id"] in _game_ids, kills))

        wins = condition(lambda row: row["win"], games)
        suicides = condition(lambda row: row["suicide"], kills)
        mafia = condition(lambda row: row["role"] == "Mafia", games)
        roles = collections.Counter([x["role"] for x in games])
        top_role = roles.most_common(1)[0]

        deaths = condition(lambda row: row["killed"] == user.id, kills)
        kills = condition(lambda row: row["killer"] == user.id, kills)

        apost = "'"  # stupid fstrings

        fmt = (
            f"{'You have' if user == ctx.author else f'{user} has'} played {len(games)} game{'s' if len(games) != 1 else ''}"
            f"{' in this server' if only_this_server else ''}, won {wins} game{'s' if wins != 1 else ''}, "
            f"killed {kills-suicides} {'people' if kills-suicides != 1 else 'person'}, died {deaths} time{'s' if deaths != 1 else ''}, committed suicide "
            f"{suicides} time{'s' if suicides != 1 else ''}, and been mafia {mafia} time{'s' if mafia != 1 else ''}.\n\n"
            f"{'Your' if user == ctx.author else f'{user.name}{apost}s'} most common role "
            f"{'here ' if only_this_server else ''}is {top_role[0]}, with {top_role[1]} game{'s' if top_role[1] != 1 else ''}."
        )
        await ctx.reply(fmt, mention_author=False)

    @commands.command("serverstats", aliases=["guildstats"])
    @commands.guild_only()
    async def guild_stats(self, ctx: Context):
        """
        Fetches stats for the current server. Cannot be used in dms.
        """
        query = """
        SELECT
            id, day_count
        FROM
            games
        WHERE
            guild_id = $1
        """

        async with ctx.acquire() as conn:
            games = await conn.fetch(query, ctx.guild.id)

            query = """
            SELECT
                game_id, user_id, win, die, players.role, r.name AS rolename
            FROM
                players
            INNER JOIN games g
                ON g.guild_id = $1
            INNER JOIN roles r
                ON r.id = players.role
            """

            players = await conn.fetch(query, ctx.guild.id)

            query = """
            SELECT
                kills.game_id, killer, killed, night, suicide, r.name AS kr_role_name, re.name as ke_role_name
            FROM
                kills
            INNER JOIN games g
                ON g.guild_id = $1
            INNER JOIN players pk
                ON pk.user_id = killed AND pk.game_id = kills.game_id
            INNER JOIN players pe
                ON pe.user_id = killed AND pk.game_id = kills.game_id
            INNER JOIN roles rk
                ON rk.id = pk.role
            INNER JOIN roles re
                ON re.id = pe.role
            """

            kills = await conn.fetch(query, ctx.guild.id)

        game_count = len(games)
        suicide_count = condition(lambda rec: rec["suicide"], kills)
        kill_count = condition(lambda rec: not rec["suicide"], kills)
        lynch_count = condition(lambda rec: rec["killer"] is None, kills)
        mafia_wins = len(
            set(x["game_id"] for x in players if x["win"] and x["role_name"] == "Mafia")
        )
        ind_wins = len(
            set(
                x["game_id"]
                for x in players
                if x["win"] and x["role_name"] not in ("Mafia", "Citizen")
            )
        )
        cit_wins = len(
            set(
                x["game_id"]
                for x in players
                if x["win"] and x["role_name"] == "Citizen"
            )
        )

        fmt = (
            f"This server has seen {game_count} game{'s' if game_count != 1 else ''}, "
            f"{suicide_count} suicide{'s' if suicide_count != 1 else ''}, "
            f"{kill_count} kill{'s' if kill_count != 1 else ''}, "
            f"{lynch_count} lynch{'es' if lynch_count != 1 else ''}, "
            f"{mafia_wins} win{'s' if mafia_wins != 1 else ''} by the mafia, "
            f"{ind_wins} win{'s' if ind_wins != 1 else ''} from independents, "
            f"and {cit_wins} win{'s' if cit_wins != 1 else ''} civilian wins."
        )
        await ctx.reply(fmt, mention_author=False)


def setup(bot: "MafiaBot"):
    bot.add_cog(Stats())
