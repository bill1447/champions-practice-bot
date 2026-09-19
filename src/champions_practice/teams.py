"""Teams used by local integration tests and early development."""

SMOKE_TEAM_ORDER = (3, 1, 2, 5)

# This is intentionally close to the current practice roster so the first full-battle
# integration test exercises Champions-specific Stat Points, terrain, and Mega Evolution.
# Showdown reuses the EVs field in team text to store Champions Stat Points.
SMOKE_TEAM = """Indeedee-F @ Colbur Berry
Ability: Psychic Surge
Level: 50
EVs: 32 HP / 32 Def / 2 Spe
Relaxed Nature
- Psychic
- Follow Me
- Trick Room
- Imprison

Sneasler @ Psychic Seed
Ability: Unburden
Level: 50
EVs: 2 HP / 32 Atk / 32 Spe
Adamant Nature
- Close Combat
- Dire Claw
- Rock Slide
- Protect

Gardevoir @ Gardevoirite
Ability: Trace
Level: 50
EVs: 4 HP / 32 SpA / 30 Spe
Modest Nature
- Expanding Force
- Hyper Voice
- Mystical Fire
- Protect

Armarouge @ Life Orb
Ability: Flash Fire
Level: 50
EVs: 32 HP / 32 SpA / 2 SpD
Quiet Nature
- Expanding Force
- Armor Cannon
- Wide Guard
- Protect

Rillaboom @ Sitrus Berry
Ability: Grassy Surge
Level: 50
EVs: 32 HP / 2 Atk / 32 SpD
Careful Nature
- Grassy Glide
- Wood Hammer
- High Horsepower
- Protect

Metagross @ Metagrossite
Ability: Clear Body
Level: 50
EVs: 2 HP / 32 Atk / 32 Spe
Adamant Nature
- Psychic Fangs
- Steel Roller
- Stomping Tantrum
- Protect
"""
