import sys
from google.cloud import firestore

# Hardcode exact GCP Project ID as required by Agent Platform
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-03-fb3ea2cda8c6"

INITIAL_ADVENTURE_SPOTS = [
    {
        "spot_id": "annapurna-circuit",
        "name": "Annapurna Circuit Trek",
        "category": "High Altitude Trekking",
        "location": "Gandaki, Nepal",
        "difficulty": "Challenging",
        "budget_per_day_usd": 30,
        "recommended_duration_days": 12,
        "description": "Legendary Himalayan trek featuring Thorong La Pass at 5,416m, rustic teahouses, and vibrant solo traveler communities.",
        "tags": ["solo-friendly", "teahouses", "trekking", "himalayas", "high-altitude"]
    },
    {
        "spot_id": "rishikesh-rafting-camping",
        "name": "Rishikesh River Rafting & Cliff Camping",
        "category": "Water & River Sports",
        "location": "Uttarakhand, India",
        "difficulty": "Moderate",
        "budget_per_day_usd": 25,
        "recommended_duration_days": 3,
        "description": "White-water rafting along the Ganges, riverside backpacker camps, cliff jumping, and spiritual evening vibes.",
        "tags": ["rafting", "camping", "budget", "water-sports", "solo-friendly"]
    },
    {
        "spot_id": "banff-skyline-backpacking",
        "name": "Banff Alpine Backpacking & Lakes",
        "category": "Mountain Backpacking",
        "location": "Alberta, Canada",
        "difficulty": "Moderate",
        "budget_per_day_usd": 65,
        "recommended_duration_days": 5,
        "description": "Glacial turquoise lakes, rugged backcountry campsites, and pristine wildlife trails through the Canadian Rockies.",
        "tags": ["mountains", "lakes", "backcountry", "wildlife", "scenic"]
    },
    {
        "spot_id": "salkantay-trek-peru",
        "name": "Salkantay Trek to Machu Picchu",
        "category": "Alpine Trekking",
        "location": "Cusco, Peru",
        "difficulty": "Challenging",
        "budget_per_day_usd": 45,
        "recommended_duration_days": 5,
        "description": "Thrilling alternative to the Inca Trail crossing high mountain passes, cloud forests, and ending at Machu Picchu.",
        "tags": ["machu-picchu", "salkantay", "alpine", "culture", "solo-friendly"]
    },
    {
        "spot_id": "torres-del-paine-w-trek",
        "name": "Torres del Paine W-Trek",
        "category": "Patagonian Wilderness",
        "location": "Magallanes, Chile",
        "difficulty": "Moderate-High",
        "budget_per_day_usd": 85,
        "recommended_duration_days": 5,
        "description": "Iconic Patagonian trail showcasing dramatic granite towers, massive glaciers, and windswept alpine valleys.",
        "tags": ["patagonia", "glaciers", "wilderness", "granite-towers"]
    }
]


def seed_database():
    print(f"Connecting to Firestore for project '{FIRESTORE_PROJECT_ID}'...")
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    collection_ref = db.collection("adventure_spots")

    print("Seeding adventure spots into Firestore...")
    for spot in INITIAL_ADVENTURE_SPOTS:
        doc_ref = collection_ref.document(spot["spot_id"])
        doc_ref.set(spot)
        print(f"  ✓ Seeded: {spot['name']} ({spot['spot_id']})")

    print("\nFirestore seeding complete! 🚀")


if __name__ == "__main__":
    seed_database()
