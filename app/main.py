"""
Run the full stub workflow for one city and print the final state.

Usage:
    python -m app.main "Nairobi"
"""

import sys
import json
import asyncio
from pathlib import Path

# Allow running as `python -m app.main` from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.state import initial_state
from app.graph import graph
from stores.graph_store import close_graphiti


def run(city_name: str) -> dict:
    print(f"\n=== Running CARDIO4Cities research workflow for '{city_name}' ===\n")
    final_state = graph.invoke(initial_state(city_name))
    asyncio.run(close_graphiti())
    print("\n=== Final state ===")
    print(json.dumps(final_state, indent=2, default=str))
    return final_state


if __name__ == "__main__":
    city = sys.argv[1] if len(sys.argv) > 1 else "Nairobi"
    run(city)
