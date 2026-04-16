"""Sample script demonstrating basic Python functions."""

from dataclasses import dataclass
from typing import List


@dataclass
class Item:
    name: str
    price: float


def calculate_total(items: List[Item]) -> float:
    """Return the total price of all items."""
    return sum(item.price for item in items)


def describe_items(items: List[Item]) -> None:
    """Print a description of each item."""
    for item in items:
        print(f"{item.name.title()} costs ${item.price:.2f}")


def main() -> None:
    """Run the sample workflow."""
    inventory = [
        Item(name="widget", price=19.99),
        Item(name="gadget", price=24.99),
        Item(name="doohickey", price=4.95),
    ]

    describe_items(inventory)
    total = calculate_total(inventory)
    print(f"\nTotal price: ${total:.2f}")


if __name__ == "__main__":
    main()
