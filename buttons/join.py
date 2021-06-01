from __future__ import annotations


from typing import List, Set, TYPE_CHECKING, cast
from discord.abc import Messageable
from discord.enums import ButtonStyle
from discord.ui import Button, button, View
from discord import Interaction, Member

if TYPE_CHECKING:
    pass


class Join(View):
    def __init__(self, amount: int, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.amount_to_join = amount
        self.players: Set[Member] = set()

    async def update_interaction(self, i: Interaction):
        if self.amount_to_join <= len(self.players):
            for child in self.children:
                cast(Button, child).disabled = True
            self.stop()
        await i.response.edit_message(
            content=f"{len(self.players)}/{self.amount_to_join} have joined", view=self
        )

    @button(label="Join", style=ButtonStyle.green)
    async def join(self, b: Button, i: Interaction):
        if isinstance(i.user, Member):
            self.players.add(i.user)
        await self.update_interaction(i)

    @button(label="Leave", style=ButtonStyle.red)
    async def leave(self, b: Button, i: Interaction):
        try:
            if isinstance(i.user, Member):
                self.players.remove(i.user)
        except KeyError:
            pass
        finally:
            await self.update_interaction(i)

    async def start(self, channel: Messageable) -> List[Member]:
        await channel.send("Press Join to join! Leave to leave!", view=self)
        await self.wait()

        return list(self.players)
