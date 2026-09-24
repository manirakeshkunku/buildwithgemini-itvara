# 🎒 ITVARA - Solo Backpacking & Adventure Travel Planner Agent

ITVARA is an intelligent, conversational travel planning agent designed specifically for solo backpackers and adventure travelers. Built with **Google's Agent Development Kit (ADK)**, ITVARA helps users explore thrill-filled itineraries, search budget hostels and hiking trails, retrieve real-time weather forecasts, convert currencies, and generate AI-powered destination images and videos—all while remembering traveler preferences and strict medical/dietary allergies across sessions.

![ITVARA Interactive Demo](demo.gif)

🎬 **Full Demo Video**: [itvara_demo.mp4](itvara_demo.mp4)

---

## 🌟 Key Capabilities & Wired Services

Based on the codebase implementation in `app/agent.py` and `frontend/`, ITVARA incorporates the following Google Cloud services, AI models, and tools:

### 🧠 1. Cross-Session Memory (Vertex AI Memory Bank)
- **Service**: `VertexAiMemoryBankService` (us-east1)
- **Functionality**: Persists traveler preferences, fitness levels, durable facts, and **strict user allergies** across conversations. Preloaded automatically on turn start via `preload_memory` tool and updated post-turn via `generate_memories_callback`.

### 🗄️ 2. Firestore Adventure Catalog (Google Cloud Firestore)
- **Service**: `google-cloud-firestore`
- **Functionality**: Stores and queries the `adventure_spots` collection. Includes tools to search destinations by category (`Trekking`, `Water Sports`, `Backpacking`), location, and daily budget (`search_adventure_spots`), fetch detailed spot profiles (`get_adventure_spot`), and contribute new spots (`add_adventure_spot`).

### 🎨 3. AI Destination Media Generation & Public Storage (GCS + Gemini)
- **Services**: Google Cloud Storage (`google-cloud-storage`), Vertex AI / Gemini APIs
- **Image Generation**: `generate_destination_image` uses `gemini-3.1-flash-lite-image` (in global region) to render custom destination artwork and wallpapers.
- **Video Generation**: `generate_adventure_video` uses Google's Omni model (`gemini-omni-flash-preview`) to generate 5-second cinematic adventure preview reels.
- **Artifacts & Cloud Storage**: Both media tools register outputs in the Playground's Artifacts panel via `tool_context.save_artifact` and upload bytes directly to a public Cloud Storage bucket, returning public `https://storage.googleapis.com/...` URLs.

### 🌤️ 4. Live Destination Weather & Exchange Rates
- **Live Weather**: `get_live_weather` fetches real-time temperature (°C) and wind speeds (km/h) for any travel hub or trail base via the Open-Meteo Geocoding & Weather API.
- **Currency Converter**: `convert_currency` calculates instant currency conversions between world currencies (NPR, INR, EUR, CAD, USD) using live exchange rates.

### 🗺️ 5. Google Maps Geocoding & Places (New)
- **Geocoding**: `geocode_address` converts landmark names or street addresses into precise latitude and longitude coordinates.
- **Places Search**: `find_nearby_places` finds nearby campgrounds, hostels, restaurants, and parks using Google Places API.

### 🎛️ 6. Native A2UI (Agent-to-User Interface)
- **Library**: `a2ui.schema.manager` (v0.8)
- **Functionality**: Formats agent recommendations into visual card surfaces (Cards, Columns, Rows, Texts, and Images) rendered directly by the frontend UI.

### 💻 7. Cloud Code Execution (Agent Engine Sandbox)
- **Executor**: `AgentEngineSandboxCodeExecutor`
- **Functionality**: Runs Python code in an isolated sandbox for trip budget allocations, expense splits, and gear weight calculations.

---

## 🏗️ Project Structure

```
itvara/
├── app/
│   ├── agent.py               # Core ADK root agent, tools, Memory Bank & GCS integration
│   ├── a2ui_utils.py          # A2UI callback and schema formatting utilities
│   └── fast_api_app.py        # FastAPI proxy application
├── frontend/
│   ├── main.py                # Proxy server bridging browser SSE streaming to A2A agent
│   ├── static/
│   │   ├── index.html         # Responsive dialogue chat layout and theme styling
│   │   ├── script.js          # Built-in A2UI card renderer & SSE event handler
│   │   └── style.css          # Modern dark-mode design system & visual tokens
├── deployment/                # Deployment configurations
├── seed_firestore.py          # Firestore database populator for adventure spots
├── record_demo.py             # Playwright browser interaction recording script
├── record_demo_with_music.py   # Automated demo video recorder
├── demo.gif                   # Looping animated preview of ITVARA in action
├── itvara_demo.mp4            # Recorded demo video (silent MP4)
├── agents-cli-manifest.yaml   # Manifest for agents-cli CLI tool
├── pyproject.toml             # Python dependencies and uv configuration
└── Dockerfile                 # Production Cloud Run deployment Dockerfile
```

---

## 🚀 Local Setup & Execution Instructions

### Prerequisites
- **Python 3.13+**
- **uv** package manager (`uv pip install ...` or `uv run ...`)
- **Google Cloud SDK** (`gcloud auth login` and `gcloud auth application-default login`)
- Configured GCP Project with Firestore, Cloud Storage, and Vertex AI APIs enabled.

### 1. Environment Configuration
Create a `.env` file in the root project directory:

```bash
FIRESTORE_PROJECT_ID="<your-gcp-project-id>"
MEDIA_BUCKET_NAME="<your-public-gcs-bucket-name>"
GOOGLE_MAPS_API_KEY="<your-google-maps-api-key>"
```

### 2. Install Dependencies & Seed Database
Install required Python packages and populate the Firestore `adventure_spots` collection:

```bash
# Install dependencies
uv sync

# Seed Firestore database with sample destinations
uv run python seed_firestore.py
```

### 3. Run Agent Backend (Development Playground)
To launch the agent locally with auto-reload:

```bash
agents-cli playground
```

Or run directly via ADK CLI:

```bash
uv run adk web app/agent.py
```

### 4. Run Custom Frontend Chat Interface
Start the FastAPI proxy server to serve the chat frontend:

```bash
cd frontend
uv run python main.py
```

Once running, navigate your web browser to the port reported by the command (default port 8080) to interact with ITVARA.

---

## ☁️ Deployment Instructions

### Deploy Agent to Vertex AI Agent Runtime
Deploy the ADK agent engine to Google Cloud:

```bash
gcloud config set project <your-gcp-project-id>
agents-cli deploy
```

### Deploy Frontend to Cloud Run
Build and ship the chat UI container to Cloud Run:

```bash
gcloud run deploy itvara-frontend \
  --source . \
  --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars AGENT_DIRECTORY=app,FIRESTORE_PROJECT_ID=<your-gcp-project-id>
```

Ensure the Cloud Run service account is granted the `roles/aiplatform.user` role to communicate with the deployed Agent Engine.

---

## 🛠️ Included Tools Reference

| Tool Name | Parameters | Description |
| --------- | ---------- | ----------- |
| `search_adventure_spots` | `category`, `location`, `max_budget_per_day` | Search Firestore for matching hiking trails & hostels |
| `get_adventure_spot` | `spot_id` | Fetch complete destination profile |
| `add_adventure_spot` | `spot_id`, `name`, `category`, `location`, `difficulty`, `budget_per_day_usd`, `description` | Add a new spot to Firestore |
| `get_live_weather` | `location_name` | Real live temperature and wind speed via Open-Meteo |
| `convert_currency` | `amount`, `from_currency`, `to_currency` | Real-time currency exchange rates |
| `geocode_address` | `address` | Convert city/landmark names to (latitude, longitude) |
| `find_nearby_places` | `latitude`, `longitude`, `place_type`, `radius_meters` | Find nearby campgrounds/lodgings via Google Places API |
| `generate_destination_image` | `prompt` | AI destination image gen (`gemini-3.1-flash-lite-image`) |
| `generate_adventure_video` | `prompt` | AI 5-second video gen (`gemini-omni-flash-preview`) |
| `preload_memory` | None | Preload user travel preferences & allergies from Memory Bank |
