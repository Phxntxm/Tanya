from __future__ import annotations
from re import I

import typing

import discord
from discord.ext import commands
from utils import AttackType, DefenseType, get_mafia_player

from mafia import role_mapping

if typing.TYPE_CHECKING:
    from mafia import MafiaGame, Role


class Player:
    dead: bool = False

    # Players that affect this player
    attacked_by: typing.Optional[Player] = None
    protected_by: typing.Optional[Player] = None
    cleaned_by: typing.Optional[Player] = None
    disguised_as: typing.Optional[Player] = None
    executionor_target: typing.Optional[Player] = None
    # Different bools for specific roles needed for each player
    doused: bool = False
    lynched: bool = False
    night_role_blocked: bool = False
    jailed: bool = False

    def __init__(
        self,
        discord_member: discord.Member | discord.User,
        ctx: commands.Context,
        role: Role,
        interaction: discord.Interaction,
    ):
        self.member = typing.cast(discord.Member, discord_member)
        self.ctx = ctx
        self.role = role
        self.visited_by: typing.List[Player] = []
        self.interaction = interaction

    def __str__(self) -> str:
        return str(self.role)

    @property
    def attack_type(self) -> AttackType:
        return self.role.attack_type

    @property
    def defense_type(self) -> DefenseType:
        return self.role.defense_type

    @property
    def attack_message(self) -> str:
        return self.role.attack_message

    @property
    def save_message(self) -> str:
        return self.role.save_message

    @property
    def suicide_message(self) -> str:
        return self.role.suicide_message

    @property
    def limit(self) -> int:
        return self.role.limit

    @property
    def short_description(self) -> str:
        return self.role.short_description

    @property
    def description(self) -> str:
        return self.role.description

    @property
    def is_godfather(self) -> bool:
        return self.role.is_godfather

    @property
    def is_jailor(self) -> bool:
        jailor_role = role_mapping.get("Jailor")
        return jailor_role is not None and isinstance(self.role, jailor_role)

    @property
    def can_kill_mafia_at_night(self) -> bool:
        return self.role.can_kill_mafia_at_night

    @property
    def win_is_multi(self) -> bool:
        return self.role.win_is_multi

    async def send_message(self, **kwargs):
        if self.interaction is not None:
            await self.interaction.followup.send(ephemeral=True, **kwargs)

    def win_condition(self, game: MafiaGame) -> bool:
        return self.role.win_condition(game, self)

    def cleanup_attrs(self):
        self.visited_by = []
        self.attacked_by = None
        self.protected_by = None
        self.night_role_blocked = False
        self.cleaned_by = None
        self.disguised_as = None
        self.jailed = False

    def protect(self, by: Player):
        self.protected_by = by
        self.visit(by)

    def kill(self, by: Player):
        self.attacked_by = by
        self.visit(by)

    def clean(self, by: Player):
        self.cleaned_by = by
        self.role.cleaned = True
        self.visit(by)

    def disguise(self, target: Player, by: Player):
        self.disguised_as = target
        self.visit(by)

    def jail(self, by: Player):
        self.jailed = True
        self.protected_by = by
        self.visit(by)

    def visit(self, by: Player):
        self.visited_by.append(by)

    @classmethod
    async def convert(cls, ctx: commands.Context, arg: str) -> typing.Optional[Player]:
        game = ctx.bot.get_cog("Mafia").games.get(ctx.guild.id)

        if game is None:
            raise commands.BadArgument(f"No game going on in this server")

        # It's a tuple of (asyncio.Task, MafiaGame)
        game = game[1]
        player = get_mafia_player(game, arg)

        raise commands.BadArgument(f"Could not find a player named {arg}")

    async def day_task(self, game: MafiaGame):
        await self.role.day_task(game, self)

    async def night_task(self, game: MafiaGame):
        await self.role.night_task(game, self)

    async def post_night_task(self, game: MafiaGame):
        await self.role.post_night_task(game, self)
