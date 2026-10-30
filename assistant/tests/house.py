"""Une maison de test, à la forme de GET /api/house (seulement les champs que l'assistant lit)."""

HOUSE = {
    "situation": {"value": "DAY", "updated_by": "UI"},
    "rooms": [
        {
            "id": "living",
            "name": "Salon",
            "occupancy": "OCCUPIED",
            "temperature": 21.4,
            "lights": [
                {
                    "id": "living_ceiling",
                    "name": "Plafond",
                    "dimmable": True,
                    "on": True,
                    "brightness_pct": 80,
                    "available": True,
                },
                {
                    "id": "living_floor",
                    "name": "Lampadaire",
                    "dimmable": True,
                    "on": False,
                    "brightness_pct": None,
                    "available": True,
                },
            ],
            "appliances": [{"id": "tv_plug", "name": "Meuble TV", "on": True, "available": True}],
            "covers": [{"id": "living_cover", "name": "Volet", "position": 100, "available": True}],
            "emitters": [{"id": "living_floor_heat", "name": "Sol du salon", "available": True}],
        },
        {
            "id": "kitchen",
            "name": "Cuisine",
            "occupancy": "VACANT",
            "lights": [{"id": "kitchen_ceiling", "name": "Plafond", "dimmable": False, "on": False, "available": True}],
            "appliances": [],
            "covers": [],
            "emitters": [],
        },
        {
            "id": "bedroom",
            "name": "Chambre",
            "occupancy": "VACANT",
            "lights": [{"id": "bed_lamp", "name": "Chevet", "dimmable": True, "on": False, "available": True}],
            "appliances": [],
            "covers": [],
            "emitters": [{"id": "bedroom_heat", "name": "Sol de la chambre", "available": True}],
        },
    ],
    "machines": [
        {
            "id": "x40",
            "name": "X40",
            "room": "living",
            "status": "DOCKED",
            "cleanable_rooms": ["living", "kitchen", "bedroom"],
        }
    ],
    "people": [{"id": "robin", "name": "Robin", "home": True}, {"id": "kim", "name": "Kim", "home": False}],
}
