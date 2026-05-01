import os
from typing import Optional, List
from dataclasses import dataclass


# Regular function
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


# Async function
async def fetch_user(user_id: int) -> Optional[dict]:
    """Fetch user by ID from the API."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"/users/{user_id}") as resp:
            return await resp.json()


# Function with type annotation
def process_items(items: List[str], separator: str = ",") -> str:
    """Join items with separator."""
    return separator.join(items)


# Generator function
def count_up_to(n: int):
    """Count from 1 to n."""
    current = 1
    while current <= n:
        yield current
        current += 1


# Inner function
def outer(x: int) -> int:
    """Outer function with inner helper."""

    def inner(y: int) -> int:
        return y * 2

    return inner(x)


# Class with inheritance
class Animal:
    """Base class for animals."""

    def __init__(self, name: str):
        self.name = name

    def speak(self) -> str:
        """Make animal sound."""
        return "..."

    @classmethod
    def create(cls, name: str) -> "Animal":
        """Factory method."""
        return cls(name)


class Dog(Animal):
    """Dog class extending Animal."""

    def __init__(self, name: str, breed: str):
        super().__init__(name)
        self.breed = breed

    def speak(self) -> str:
        return "Woof!"

    @staticmethod
    def is_mammal() -> bool:
        """Check if dog is a mammal."""
        return True


# Decorated function
@dataclass
class Config:
    """Configuration dataclass."""
    host: str = "localhost"
    port: int = 8080
