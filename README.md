# XenStrategist
A LangGraph Multi-Agent Decision-Support Platform for B2B SaaS Customer Success Prioritization

Website: https://xenstrategist.onrender.com/


## Overview
Xenstrategist is a Customer Success Manager (CSM) decision-support tool designed for B2B SaaS organizations to prioritize and execute customer-success mitigations. By processing raw CRM transcripts, notes, and emails through a cooperative multi-agent pipeline, the system generates prioritized, explainable next-best-action recommendations. With human-in-the-loop validation, CSMs can inspect underlying assumptions, run what-if simulations, and modify parameters to ensure high-confidence customer retention and expansion.

<img width="8192" height="5344" alt="image" src="https://github.com/user-attachments/assets/fe17a664-2828-46ee-b9d0-d75946d8d8d4" />

## How It Works
The platform relies on a hub-and-spoke LangGraph orchestration model, coordinated by a central planner that routes execution context to specialized spokes and pauses at human checkpoints:

* **Planner Agent**: Inspects the incoming case state, dynamically routes to the appropriate agents via LangGraph's `Command(goto=...)`, and logs each routing decision alongside its internal confidence reasoning into the `plan_trace` state (which powers the "Plan Trace" UI panel for full pipeline transparency).
* **Ingestion & Context Agent**: Uses Groq with Llama 3.3 70B to parse raw CRM text, transcripts, and notes into a structured `customer_profile`, identifying key metrics such as health scores, subscription tiers, and active users, while explicitly flagging inferred or uncertain values as "assumptions". A regex-based mock parser is provided as a fallback if `GROQ_API_KEY` is not configured.
* **Knowledge Retrieval Agent**: Queries a Chroma DB `knowledge_base` collection containing playbooks, escalation guidelines, and retention policies. It re-ranks retrieved search results using a custom time-decay weighting function, ensuring that recently updated policies and playbooks take precedence over older documents of similar semantic relevance.
* **Reasoning & Arbitration Agent**: Computes the prioritized action using the PCVL formula: `Priority = Propensity x Context x Value x Levers`. The `Context` value is dynamically calculated and time-decayed based on retrieved evidence. If a CSM edits any ingestion assumptions, the graph triggers an automatic loopback from execution to reasoning to re-evaluate the priority and recommendation.
* **Explainability Agent**: Generates a clear, human-readable rationale and defense of the recommended action. It assigns an overall confidence score and explicitly flags low-confidence scenarios, prompting the CSM with caveats and risk alerts rather than presenting false certainty.
* **Memory Update Agent**: Executed only upon explicit CSM approval. It writes the finalized case metadata, recommendation, and eventual outcome to the Chroma `interaction_history` collection. It also exposes a similarity search (`find_similar_past_cases()`) to match current cases against past decisions, which powers the "Memory Diff" panel in the UI.

## Tech Stack

| Component | Technology | Purpose |
| :--- | :--- | :--- |
| **Orchestration** | LangGraph | State graph execution, MemorySaver checkpointing, and `interrupt`/`resume` human-in-the-loop control flow. |
| **LLM Inference** | Groq API & Llama 3.3 70B | High-performance extraction of customer profiles, assumptions, and explanation generation. |
| **Vector Database** | ChromaDB | Persistent storage for `knowledge_base` (playbooks) and `interaction_history` (CSM decisions). |
| **Backend API** | FastAPI | High-speed endpoints (`/process`, `/resume`, `/memory_diff`) driving the graph execution and frontend state sync. |
| **Frontend Dashboard** | Streamlit | CSM-facing control center visualizing CRM notes, PCVL metrics, Plan Trace, Memory Diff, and HITL actions. |
| **Runtime / Language** | Python 3.11+ | Core language stack and package manager environment. |

## Key Features
* **Plan Trace Panel**: Visualizes the internal routing decisions and confidence logs of the central Planner Agent as it steps through the pipeline.
* **Memory Diff Panel**: Surfaces highly relevant historical cases and their human decisions (approved/modified/rejected) to prevent repeat failures and standard playbook traps.
* **Confidence-Aware Escalation**: Automatically flags low-confidence cases with detailed caveats, requesting human intervention when evidence is sparse.
* **Visible PCVL Math**: Unpacks the prioritization calculation (`Priority = Propensity × Context × Value × Levers`) in real-time, displaying how context and risk variables combine.
* **Time-Decay Weighting**: Employs a custom decay function during playbook retrieval and reasoning context scores to prioritize fresh knowledge and recent evidence.
* **Edit → Re-Reasoning Loop**: Allows the CSM to patch inferred customer profile assumptions and automatically re-run the reasoning and explainability agents to display side-by-side comparisons of original vs. corrected actions.

## Project Structure
```text
Xen/
├── agents/                      # LangGraph agent definitions
│   ├── explainability.py        # Generates recommendation rationale & confidence
│   ├── graph.py                 # Main LangGraph pipeline & compilation
│   ├── ingestion.py             # Groq/fallback parsing of raw text
│   ├── memory_update.py         # DB writes and past-case similarity search
│   ├── planner.py               # Hub-and-spoke central router agent
│   ├── reasoning.py             # Prioritization engine calculating PCVL math
│   └── retrieval.py             # ChromaDB query logic with time-decay ranking
├── api/                         # Backend routes and FastAPI setup
│   └── main.py                  # API endpoints (/process, /resume, /memory_diff)
├── ui/                          # Streamlit frontend application
│   ├── app.py                   # UI dashboard layout and event handlers
│   └── style.css                # Premium styling sheets
├── data/
│   └── scenarios/               # Standard customer case presets and playbooks
│       ├── knowledge_base_docs.json  # Seed documents for retrieval
│       ├── scenario_1_churn.json
│       ├── scenario_2_expansion.json
│       ├── scenario_3_ambiguous.json
│       ├── scenario_4_apexlogistics_followup.json
│       └── scenario_5_novaretail_enterprise.json
├── scripts/                     # Operational automation scripts
│   ├── run_scenario.py          # CLI runner for test cases
│   ├── seed_interaction_history.py  # Populates past interaction memory
│   └── seed_knowledge_base.py   # Populates the playbook collection
├── chroma_store/                # Local Chroma database directory (gitignored)
├── requirements.txt             # Primary package dependencies
├── .env.example                 # Environment configuration template
└── README.md                    # Repository documentation
```

## Setup & Installation

Follow these steps to set up and run the project locally:

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd Xen
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   ```
   Activate the virtual environment:
   * **Windows (PowerShell):**
     ```powershell
     .venv\Scripts\Activate.ps1
     ```
   * **macOS/Linux:**
     ```bash
     source .venv/bin/activate
     ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Copy the environment template and set your API keys:
   ```bash
   # Windows:
   copy .env.example .env
   # macOS/Linux:
   cp .env.example .env
   ```
   Edit the `.env` file and input your `GROQ_API_KEY`. If you do not configure a key, the system will seamlessly run using its regex-based mock profile parser fallback.

5. **Seed the database collections:**
   Run the seeding scripts to initialize the knowledge base playbooks and historical case memories in ChromaDB:
   ```bash
   python scripts/seed_knowledge_base.py
   python scripts/seed_interaction_history.py
   ```

6. **Start the FastAPI backend:**
   Run the backend API using Uvicorn on port 8000:
   ```bash
   uvicorn api.main:app --port 8000
   ```

7. **Start the Streamlit frontend dashboard:**
   In a new terminal window/tab (with virtual environment activated), start the user interface:
   ```bash
   streamlit run ui/app.py
   ```
   The dashboard will automatically open in your browser, typically at `http://localhost:8501`.

## Screenshots
<img width="1882" height="988" alt="image" src="https://github.com/user-attachments/assets/6d18c851-222b-4130-8a63-a4c90e9681b7" />
<img width="1716" height="1026" alt="image" src="https://github.com/user-attachments/assets/3b93faeb-0e81-44dc-8764-aaf68b7a4960" />
<img width="1495" height="1040" alt="image" src="https://github.com/user-attachments/assets/dec0c7b9-433f-4e03-a89b-19cfa4621b8f" />
<img width="1898" height="1042" alt="image" src="https://github.com/user-attachments/assets/eca84eb4-1d6b-4873-9c37-5dbf4682f104" />


