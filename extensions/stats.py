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
        if user is None:
            _user = ctx.author
        else:
            _user = user

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
            games = await conn.fetch(query, _user.id)

            query = """
            SELECT
                game_id, killer, killed, night, suicide
            FROM kills
            WHERE
                killer = $1 OR killed = $1
            """
            kills = await conn.fetch(query, _user.id)

        if not games:
            return await ctx.reply(f"No stats for {_user}", mention_author=False)

        if only_this_server:
            games = list(filter(lambda row: row["guild_id"] == ctx.guild.id, games))
            _game_ids = tuple(x["id"] for x in games)
            kills = list(filter(lambda row: row["game_id"] in _game_ids, kills))

        wins = condition(lambda row: row["win"], games)
        suicides = condition(lambda row: row["suicide"], kills)
        mafia = condition(lambda row: row["role"] == "Mafia", games)
        roles = collections.Counter([x["role"] for x in games])
        top_role = roles.most_common(1)[0]

        deaths = condition(lambda row: row["killed"] == _user.id, kills)
        kills = condition(lambda row: row["killer"] == _user.id, kills)

        apost = "'"  # stupid fstrings

        fmt = (
            f"{'You have' if _user == ctx.author else f'{_user} has'} played {len(games)} game{'s' if len(games) != 1 else ''}"
            f"{' in this server' if only_this_server else ''}, won {wins} game{'s' if wins != 1 else ''}, "
            f"killed {kills-suicides} {'people' if kills-suicides != 1 else 'person'}, died {deaths} time{'s' if deaths != 1 else ''}, committed suicide "
            f"{suicides} time{'s' if suicides != 1 else ''}, and been mafia {mafia} time{'s' if mafia != 1 else ''}.\n\n"
            f"{'Your' if _user == ctx.author else f'{_user.name}{apost}s'} most common role "
            f"{'here ' if only_this_server else ''}is {top_role[0]}, with {top_role[1]} game{'s' if top_role[1] != 1 else ''}."
        )
        await ctx.reply(fmt, mention_author=False)

    @commands.command("serverstats", aliases=["guildstats"])
    @commands.guild_only()
    async def guild_stats(self, ctx: Context):
        """
        Fetches stats for the current server. Cannot be used in dms.
        """

        async with ctx.acquire() as conn:
            query = """
            SELECT
                games.id,
                players.user_id,
                roles.alignment,
                players.win,
                players.die,
                kills.killer,
                kills.suicide,
                kills.lynch
            FROM
                players
            LEFT JOIN games
                ON games.id = players.game_id
            LEFT JOIN roles
                ON roles.id = players.role
            LEFT JOIN kills
                ON killed = players.user_id AND kills.game_id = games.id
            WHERE games.guild_id = $1
            """

            players = await conn.fetch(query, ctx.guild.id)

        games = set()
        suicide_count = kill_count = lynch_count = mafia_wins = ind_wins = cit_wins = 0

        for row in players:
            games.add(row["id"])
            if row["suicide"]:
                suicide_count += 1
            if row["killer"]:
                suicide_count += 1
            if row["lynch"]:
                lynch_count += 1
            if row["win"] and row["alignment"] == 3:
                mafia_wins += 1
            if row["win"] and row["alignment"] == 2:
                ind_wins += 1
            if row["win"] and row["alignment"] == 1:
                cit_wins += 1

        game_count = len(games)

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
