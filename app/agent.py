# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo
import dotenv
import requests

import google.auth
import google.auth.transport.requests
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory.vertex_ai_memory_bank_service import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext, preload_memory
from google.cloud import firestore, storage
from google.genai import types

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager

from app.a2ui_utils import a2ui_callback

dotenv.load_dotenv()

# Hardcode exact GCP project ID and Cloud Storage Bucket name as strings
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-03-fb3ea2cda8c6"
MEDIA_BUCKET_NAME = "itvara-media-qwiklabs-gcp-03-fb3ea2cda8c6"

# Load Agent Engine resource name from deployment_metadata.json
DEPLOYMENT_METADATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "deployment_metadata.json"
)
AGENT_ENGINE_RESOURCE_NAME = (
    "projects/30471912245/locations/us-east1/reasoningEngines/1189154810788577280"
)
if os.path.exists(DEPLOYMENT_METADATA_FILE):
    try:
        with open(DEPLOYMENT_METADATA_FILE, "r") as f:
            metadata = json.load(f)
            AGENT_ENGINE_RESOURCE_NAME = metadata.get(
                "remote_agent_runtime_id", AGENT_ENGINE_RESOURCE_NAME
            )
    except Exception:
        pass

# Memory Bank ID from deployed Agent Engine (last part of remote_agent_runtime_id)
MEMORY_BANK_ID = AGENT_ENGINE_RESOURCE_NAME.split("/")[-1]


def memory_bank_service_builder():
    """Returns a VertexAiMemoryBankService instance configured for this Agent Engine."""
    return VertexAiMemoryBankService(
        project=FIRESTORE_PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


async def generate_memories_callback(callback_context: CallbackContext):
    """WRITE callback: sends session events to Memory Bank for fact and allergy extraction after each turn."""
    try:
        await callback_context.add_session_to_memory()
    except Exception:
        pass
    return None


def _get_firestore_db() -> firestore.Client:
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


def search_adventure_spots(
    category: str = None, location: str = None, max_budget_per_day: float = None
) -> str:
    """Search and list adventure spots, hiking trails, and solo backpacking destinations from Firestore.

    Args:
        category: Optional filter by category (e.g. 'Trekking', 'Water Sports', 'Backpacking').
        location: Optional filter by location name or country (e.g. 'Nepal', 'India', 'Canada').
        max_budget_per_day: Optional maximum budget per day in USD.

    Returns:
        A formatted string or list of matching adventure spots.
    """
    db = _get_firestore_db()
    collection_ref = db.collection("adventure_spots")
    docs = collection_ref.stream()

    results = []
    for doc in docs:
        spot = doc.to_dict()
        if category and category.lower() not in spot.get("category", "").lower() and category.lower() not in " ".join(spot.get("tags", [])).lower():
            continue
        if location and location.lower() not in spot.get("location", "").lower():
            continue
        if max_budget_per_day is not None and spot.get("budget_per_day_usd", 0) > max_budget_per_day:
            continue
        results.append(spot)

    if not results:
        return "No adventure spots found matching the criteria."
    return str(results)


def get_adventure_spot(spot_id: str) -> str:
    """Get detailed information for a specific adventure spot by its spot_id.

    Args:
        spot_id: Unique document ID for the spot (e.g. 'annapurna-circuit', 'rishikesh-rafting-camping').

    Returns:
        Details of the adventure spot or an error message if not found.
    """
    db = _get_firestore_db()
    doc_ref = db.collection("adventure_spots").document(spot_id)
    doc = doc_ref.get()
    if not doc.exists:
        return f"Adventure spot '{spot_id}' not found."
    return str(doc.to_dict())


def add_adventure_spot(
    spot_id: str,
    name: str,
    category: str,
    location: str,
    difficulty: str,
    budget_per_day_usd: float,
    description: str,
    recommended_duration_days: int = 3,
    tags: str = None,
) -> str:
    """Add a new adventure spot destination or hostel base to Firestore.

    Args:
        spot_id: Unique identifier string for the spot (lowercase hyphens, e.g. 'bali-surf-camp').
        name: Display name of the destination/spot.
        category: Adventure category (e.g. 'Trekking', 'Surfing', 'Backcountry').
        location: City, Region, or Country.
        difficulty: Trip difficulty rating (e.g. 'Easy', 'Moderate', 'Challenging').
        budget_per_day_usd: Estimated budget per day in USD.
        description: Brief overview of the spot for solo travelers.
        recommended_duration_days: Suggested trip length in days.
        tags: Comma-separated tags (e.g. 'solo-friendly,surfing,budget').

    Returns:
        Confirmation message.
    """
    db = _get_firestore_db()
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    spot_data = {
        "spot_id": spot_id,
        "name": name,
        "category": category,
        "location": location,
        "difficulty": difficulty,
        "budget_per_day_usd": budget_per_day_usd,
        "recommended_duration_days": recommended_duration_days,
        "description": description,
        "tags": tag_list,
    }
    db.collection("adventure_spots").document(spot_id).set(spot_data)
    return f"Successfully added adventure spot '{name}' ({spot_id}) to Firestore."


def convert_currency(
    amount: float, from_currency: str, to_currency: str = "USD"
) -> str:
    """Converts an amount from one currency to another using live exchange rates.

    Args:
        amount: Numerical amount to convert (e.g. 5000.0).
        from_currency: 3-letter source currency code (e.g. 'NPR', 'INR', 'CAD', 'EUR').
        to_currency: 3-letter target currency code (default 'USD').

    Returns:
        A string with the converted amount and current exchange rate.
    """
    from_code = from_currency.upper().strip()
    to_code = to_currency.upper().strip()
    url = f"https://open.er-api.com/v6/latest/{from_code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ITVARA-Agent"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        if data.get("result") != "success":
            return f"Unable to fetch exchange rates for {from_code}."

        rates = data.get("rates", {})
        if to_code not in rates:
            return f"Target currency '{to_code}' not found."

        rate = rates[to_code]
        converted_amount = round(amount * rate, 2)
        return f"{amount} {from_code} = {converted_amount} {to_code} (1 {from_code} = {rate} {to_code})"
    except Exception as e:
        return f"Error performing currency conversion: {str(e)}"


def get_live_weather(location_name: str) -> str:
    """Fetches real live weather conditions (temperature in °C, wind speed in km/h) for any travel destination or trail base.

    Args:
        location_name: City, region, or landmark name (e.g. 'Pokhara', 'Rishikesh', 'Banff', 'Cusco', 'Kathmandu').

    Returns:
        A string containing real live weather details.
    """
    loc = location_name.strip()
    api_key = os.getenv("OPEN_METEO_API_KEY", "")
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(loc)}&count=1"
        req_geo = urllib.request.Request(geo_url, headers=headers)
        with urllib.request.urlopen(req_geo, timeout=5) as resp:
            geo_data = json.loads(resp.read().decode())

        if not geo_data.get("results"):
            return f"Could not find coordinates for location '{location_name}'."

        res = geo_data["results"][0]
        lat, lon = res["latitude"], res["longitude"]
        country = res.get("country", "")
        full_name = f"{res.get('name', loc)}, {country}" if country else res.get("name", loc)

        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        if api_key:
            weather_url += f"&apikey={api_key}"

        req_w = urllib.request.Request(weather_url, headers=headers)
        with urllib.request.urlopen(req_w, timeout=5) as resp_w:
            w_data = json.loads(resp_w.read().decode())

        cw = w_data.get("current_weather", {})
        temp = cw.get("temperature")
        wind = cw.get("windspeed")
        return f"Live weather for {full_name}: {temp}°C, Wind Speed: {wind} km/h."
    except Exception as e:
        return f"Error fetching live weather for {location_name}: {str(e)}"


def geocode_address(address: str) -> str:
    """Converts a location name or street address into geographic coordinates (latitude, longitude) using Google Maps Geocoding API.

    Args:
        address: Location name, city, or address (e.g. 'Thamel, Kathmandu', 'Banff, Canada', 'Rishikesh, India').

    Returns:
        Formatted string with location name, latitude, longitude, and formatted address.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not configured."

    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={api_key}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        if data.get("status") != "OK" or not data.get("results"):
            return f"Could not geocode address '{address}': {data.get('status', 'ZERO_RESULTS')}"

        result = data["results"][0]
        fmt_address = result.get("formatted_address")
        location = result.get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        return f"Geocoded '{address}': Address='{fmt_address}', Latitude={lat}, Longitude={lng}"
    except Exception as e:
        return f"Error geocoding address '{address}': {str(e)}"


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "campground",
    radius_meters: float = 5000.0,
) -> str:
    """Finds nearby places of a specific type (e.g. 'campground', 'lodging', 'restaurant', 'tourist_attraction', 'park') using Google Places API (New).

    Args:
        latitude: Latitude coordinate of center search point.
        longitude: Longitude coordinate of center search point.
        place_type: Place type string (e.g. 'campground', 'lodging', 'restaurant', 'tourist_attraction', 'park').
        radius_meters: Search radius in meters (default 5000.0, max 50000.0).

    Returns:
        Formatted list of key place details (name, formatted address, location).
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not configured."

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.types",
    }
    body_data = {
        "includedTypes": [place_type.lower().strip()],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": radius_meters,
            }
        },
    }

    try:
        req = urllib.request.Request(
            url, data=json.dumps(body_data).encode("utf-8"), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        places = data.get("places", [])
        if not places:
            return f"No nearby places of type '{place_type}' found within {radius_meters}m of ({latitude}, {longitude})."

        results = []
        for p in places:
            name = p.get("displayName", {}).get("text", "Unknown Name")
            addr = p.get("formattedAddress", "N/A")
            loc = p.get("location", {})
            results.append({
                "name": name,
                "address": addr,
                "location": {
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                },
            })
        return str(results)
    except Exception as e:
        return f"Error finding nearby places: {str(e)}"


async def generate_destination_image(
    prompt: str, tool_context: ToolContext = None
) -> str:
    """Generates an image for an adventure destination, trail, or travel scene using the gemini-3.1-flash-lite-image model in global region, saves it as an artifact in Playground, and uploads it to Cloud Storage.

    Args:
        prompt: Descriptive text prompt for the image (e.g. 'A scenic illustration of Annapurna Circuit trek in Nepal with solo backpackers').
        tool_context: ToolContext instance provided automatically by the ADK framework.

    Returns:
        The public HTTPS URL of the uploaded image.
    """
    try:
        genai_client = genai.Client(location="global", project=FIRESTORE_PROJECT_ID)
        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )

        image_bytes = None
        mime_type = "image/jpeg"
        if response.parts:
            for part in response.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or "image/jpeg"
                    break

        if not image_bytes:
            return "Error: Model did not return any image data."

        ext = "jpg" if "jpeg" in mime_type.lower() else "png"
        filename = f"adventure_{uuid.uuid4().hex[:8]}.{ext}"

        # 1. Save artifact to Playground's Artifacts panel via tool_context if available
        if tool_context:
            artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload image bytes directly to public GCS bucket (no local file write)
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(MEDIA_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{MEDIA_BUCKET_NAME}/{filename}"
        return f"Successfully generated destination image: {public_url}"
    except Exception as e:
        return f"Error generating destination image: {str(e)}"


async def generate_adventure_video(
    prompt: str, tool_context: ToolContext = None
) -> str:
    """Generates a short video for an item in ITVARA's domain (adventure spot, hiking trail, scenic landscape, or travel reel) using Google's Omni model (gemini-omni-flash-preview) in the global region, saves it as an artifact in Playground, and uploads it to public Cloud Storage.

    Args:
        prompt: Detailed text prompt describing the travel or adventure video scene (e.g. 'A 5-second cinematic drone video of Annapurna trail in Nepal').
        tool_context: ToolContext instance provided automatically by the ADK framework.

    Returns:
        The public HTTPS URL of the uploaded video (https://storage.googleapis.com/itvara-media-qwiklabs-gcp-03-fb3ea2cda8c6/filename.mp4).
    """
    try:
        credentials, project = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        token = credentials.token

        url = f"https://aiplatform.googleapis.com/v1beta1/projects/{FIRESTORE_PROJECT_ID}/locations/global/interactions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "model": "gemini-omni-flash-preview",
            "input": [{"type": "text", "text": prompt}],
            "response_format": [{"type": "video", "aspect_ratio": "16:9", "duration": "5s"}],
            "generation_config": {"video_config": {"task": "text_to_video"}},
        }

        res = requests.post(url, headers=headers, json=payload, timeout=120)
        res_data = res.json()

        video_bytes = None
        if "output_video" in res_data and "data" in res_data["output_video"]:
            video_bytes = base64.b64decode(res_data["output_video"]["data"])
        elif "steps" in res_data:
            for step in res_data["steps"]:
                for item in step.get("content", []):
                    if item.get("type") == "video" and "data" in item:
                        video_bytes = base64.b64decode(item["data"])
                        break
                    elif item.get("type") == "video" and "bytes" in item:
                        video_bytes = base64.b64decode(item["bytes"])
                        break
                    elif item.get("type") == "video" and "uri" in item:
                        gcs_uri = item["uri"]
                        if gcs_uri.startswith("gs://"):
                            parts = gcs_uri[5:].split("/", 1)
                            st_client = storage.Client(project=FIRESTORE_PROJECT_ID)
                            b = st_client.bucket(parts[0])
                            video_bytes = b.blob(parts[1]).download_as_bytes()
                        break

        if not video_bytes:
            # Fallback to genai.Client
            genai_client = genai.Client(location="global", project=FIRESTORE_PROJECT_ID)
            if hasattr(genai_client, "interactions"):
                int_res = genai_client.interactions.create(
                    model="gemini-omni-flash-preview",
                    input=prompt,
                    response_format={"type": "video", "aspect_ratio": "16:9"},
                )
                if hasattr(int_res, "output_video") and getattr(int_res.output_video, "data", None):
                    video_bytes = base64.b64decode(int_res.output_video.data)

        if not video_bytes:
            return f"Error generating video with gemini-omni-flash-preview: {res.text}"

        filename = f"adventure_video_{uuid.uuid4().hex[:8]}.mp4"
        mime_type = "video/mp4"

        # 1. Save artifact to Playground's Artifacts panel via tool_context
        if tool_context:
            artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
            await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload video bytes directly to public GCS bucket (no local file write)
        storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
        bucket = storage_client.bucket(MEDIA_BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{MEDIA_BUCKET_NAME}/{filename}"
        return f"Successfully generated adventure video: {public_url}"
    except Exception as e:
        return f"Error generating adventure video: {str(e)}"


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=AGENT_ENGINE_RESOURCE_NAME,
)

schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are ITVARA, an expert travel planner agent specializing in solo backpacking and adventure trips. "
        "When greeted (e.g., 'Hi', 'Hello', 'Hey'), welcome the user warmly to ITVARA, introduce yourself, and ask how you can assist with their solo travel or adventure plans. "
        "For all specific user questions (e.g. destinations, weather, budget, packing, itineraries, or specific locations), answer their exact query directly and dynamically using your tools and knowledge. "
        "Use your Memory Bank to remember traveler preferences, durable facts, and ALL USER ALLERGIES or dietary/medical restrictions across conversations. "
        "Pay strict attention to any allergies mentioned by the user and ensure all itinerary, meal, food, outdoor trail, and accommodation recommendations strictly respect them."
    ),
    workflow_description=(
        "Analyze the user's exact request carefully. "
        "If greeted, provide a warm welcome greeting surface. "
        "If asked a specific question, invoke relevant tools (search_adventure_spots, get_adventure_spot, add_adventure_spot, convert_currency, "
        "get_live_weather, geocode_address, find_nearby_places, generate_destination_image, generate_adventure_video) or execute code to fetch live data and answer their specific request thoroughly."
    ),
    ui_description=(
        "Keep every surface tiny, clean, and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use Table or Heading (unsupported), or Buttons, actions, or forms. "
        "You may include one Image component, but only when you have a public https URL for the image. Set the Image url to that exact https link. Never point an Image at a bare filename or artifact name. If you do not have a public URL, add a short Text line noting the image instead. "
        "No markdown syntax inside Text literalStrings; use the usageHint property ('h1', 'h2', 'body', 'caption') for titles, headings, and text formatting. "
        "Output ONLY the raw A2UI JSON array — no raw prose outside the JSON array, and never wrap it in <a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=a2ui_instruction,
    code_executor=code_executor,
    tools=[
        search_adventure_spots,
        get_adventure_spot,
        add_adventure_spot,
        convert_currency,
        get_live_weather,
        geocode_address,
        find_nearby_places,
        generate_destination_image,
        generate_adventure_video,
        get_current_time,
        preload_memory,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
