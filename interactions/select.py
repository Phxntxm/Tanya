from __future__ import annotations


from typing import Any, List, TYPE_CHECKING, Tuple, cast, Any
from discord.components import SelectOption
from discord.ui import View, select, Select
from discord import Interaction

if TYPE_CHECKING:
    from mafia import Player, MafiaGame


class SelectView(View):
    def __init__(
        self,
        message: str,
        choices: List[Any],
        inter: Interaction,
        *args,
        min_selection=1,
        max_selection=1,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.starting_message = message
        self.choose.options = [SelectOption(label=c) for c in choices]
        self.inter = inter
        self.last_interaction: Interaction | None

        self.choose.min_values = min_selection
        self.choose.max_values = max_selection

    @select(placeholder="Choose")
    async def choose(self, s: Select, i: Interaction):
        self.last_interaction = i

    async def start(self) -> List[str]:
        await self.inter.followup.send(self.starting_message, view=self, ephemeral=True)

        if not await self.wait():
            return self.choose.values
        else:
            return []


class DisguiserSelect(View):
    def __init__(
        self,
        message: str,
        mafia_choices: List[Any],
        nonmafia_choices: List[Any],
        inter: Interaction,
        *args,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.starting_message = message
        self.inter = inter

        self.choose_mafia.options = [SelectOption(label=c) for c in mafia_choices]
        self.choose_nonmafia.options = [SelectOption(label=c) for c in nonmafia_choices]

    @select(placeholder="Choose user to disguise")
    async def choose_mafia(self, s: Select, i: Interaction):
        self.last_interaction = i

    @select(placeholder="Choose user to disguise as")
    async def choose_nonmafia(self, s: Select, i: Interaction):
        self.last_interaction = i

    async def start(self) -> Tuple[str, str] | None:
        await self.inter.followup.send(self.starting_message, view=self, ephemeral=True)

        if not await self.wait():
            return self.choose_mafia.values[0], self.choose_nonmafia.values[0]


async def player_select(
    player: Player,
    game: MafiaGame,
    starting_message: str,
    choices: List[Any],
    timeout: int = None,
) -> str | None:
    view = SelectView(starting_message, choices, player.interaction, timeout=timeout)
    choice = await view.start()
    # Update the member's interaction to this one to refresh followups
    if view.last_interaction is not None:
        game.inter_mapping[player.member.id] = view.last_interaction

    return choice[0]
