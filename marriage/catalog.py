from dataclasses import dataclass


@dataclass(frozen=True)
class Gift:
    name: str
    emoji: str
    price: int
    description: str
    ring: bool = False

    @property
    def label(self):
        return f"{self.emoji} {self.name}"


CATALOG = {
    "coffee": Gift("Coffee", "☕", 25, "A small pick-me-up."),
    "chocolates": Gift("Chocolate Box", "🍫", 60, "Something sweet to share."),
    "flowers": Gift("Rose Bouquet", "💐", 100, "A classic bunch of roses."),
    "fox": Gift("Plush Fox", "🦊", 175, "A pocket-sized woodland friend."),
    "locket": Gift("Engraved Locket", "✨", 275, "A keepsake for an anniversary."),
    "band": Gift("Gold Band", "💍", 350, "A simple gold proposal ring.", ring=True),
    "sapphire": Gift("Sapphire Ring", "💎", 700, "A deep-blue proposal ring.", ring=True),
}
