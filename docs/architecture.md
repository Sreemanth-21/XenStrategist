# Xen Architecture Documentation

This document describes the orchestration, reasoning, and component architecture of the **Xen** platform (represented in the UI as **Pulse**). Xen is a Next Best Action (NBA) platform built for B2B SaaS Customer Success Managers (CSMs) to proactively prevent churn, identify upsell opportunities, and manage customer interactions.

---

## 1. High-Level Architecture Overview

Xen uses a dynamic, stateful **Hub-and-Spoke** agent design built on **LangGraph**. A central programmatic **Planner Agent** (the Hub) evaluates the current state of a case and decides which specialized domain agent (the Spoke) to route to next.

### Orchestration State (`PulseState`)
The global state schema driving the orchestration contains the following fields:
*   `case_id`: Unique identifier for the current CRM touchpoint thread.
*   `raw_input`: Unstructured interaction text (e.g., call transcript, CRM note, email).
*   `customer_profile`: Structured data parsed from the input (e.g., ARR, health score, risk level).
*   `assumptions`: Flagged items that were inferred/assumed due to missing or ambiguous source details.
*   `retrieved_evidence`: Contextual playbooks and historical guidelines retrieved from the knowledge store.
*   `recommendation`: Multi-dimensional output containing the recommended action, priority metrics, and confidence details.
*   `explanation`: Synthesized human-readable rationale explaining the recommendation.
*   `plan_trace`: Programmatic log of routing decisions and agent interactions.
*   `status`: Current thread state (`"new"`, `"pending_review"`, `"approved"`, `"edited"`, `"rejected"`, or `"executed"`).
*   `human_decision`: Payload capturing approval, rejection, or edit overrides during human-in-the-loop validation.

---

## 2. Orchestration Graph Flow

Below is the orchestration lifecycle of a case, illustrating the Hub-and-Spoke interactions and the Human-in-the-Loop (HITL) interrupt barrier:

![Xen Orchestration Graph Flow](https://github.com/user-attachments/assets/fe17a664-2828-46ee-b9d0-d75946d8d8d4)

---

## 3. Core Agent Modules & Operations

### A. Ingestion & Context Agent
*   **Role**: Converts unstructured natural language customer touchpoints into a validated, structured object.
*   **Logic**:
    1. Parses CRM inputs using `llama-3.3-70b-versatile` (or falls back to mock loaders based on `case_id`).
    2. Maps data into the customer profile schema: `company_name`, `contract_value`, `contract_type`, `health_score`, `segment`, `churn_risk`, `license_count`, `active_users`.
    3. Identifies ambiguous fields (e.g., unclear contract duration or inferred health signals) and tracks them in `assumptions` to preserve transparency.

### B. Knowledge Retrieval Agent
*   **Role**: Gathers historical playbooks and guidelines relevant to the customer's current risk segment.
*   **Logic**:
    1. Constructs a semantic search query based on customer attributes (e.g., `"{segment} customer, {churn_risk} churn risk, {contract_type} contract"`).
    2. Queries the vector database (ChromaDB `knowledge_base` collection) to retrieve the top 6 matches.
    3. Applies a **Time-Decay Re-Ranking** score to prioritize fresher documents:
       $$\text{decayed\_score} = \text{similarity\_score} \times e^{-0.01 \times \text{age\_in\_days}}$$
    4. Filters and returns the top 4 re-ranked documents. If average score is under `0.40`, triggers a broader query query retry via the Planner.

### C. Reasoning & Arbitration Agent
*   **Role**: Determines the priority score, identifies the optimal next best action, and computes recommendation confidence.
*   **PCVL Priority Framework**:
    The system determines case priority dynamically based on:
    $$\text{Priority} = \text{Propensity} (P) \times \text{Context} (C) \times \text{Value} (V) \times \text{Levers} (L)$$

    1.  **Propensity (P)**: Baseline likelihood to respond to action, mapped from `churn_risk` (High: `0.85`, Medium: `0.50`, Low: `0.20`), and nudged by the customer health score (up to $\pm 0.15$ points).
    2.  **Context (C)**: Alignment score of playbooks retrieved, measured as the average decayed score of the top retrieved playbooks.
    3.  **Value (V)**: Account contract value normalized relative to a ceiling of $\$200,000$, capped at `1.0`.
    4.  **Levers (L)**: Represents standard actionability. Score is `0.8` if a matched recovery/upsell playbook is present in retrieved evidence, and `0.4` if missing.
*   **Confidence Score & Penalties**:
    Measures overall structural trustworthiness of the recommendation:
    $$\text{Confidence} = \max\left(0.1, \min\left(1.0, (0.4 + 0.6 \times \text{Context}) - \text{Total Deductions}\right)\right)$$
    *   *Assumption Penalty*: $-0.05$ deduction for each inferred assumption in the profile (capped at $-0.15$).
    *   *Weak Evidence Penalty*: $-0.20$ deduction if retrieved evidence is empty or Context is weak ($\le 0.15$).
    *   *Manual Review Penalty*: $-0.15$ deduction if the resulting action requires complex human arbitration.
*   **Guidance Overrides**:
    Accepts natural language CSM overrides (e.g., "force upsell", "change churn risk to High") to re-evaluate the calculation parameters. When guidance is applied, the agent automatically clears corresponding unverified profile assumptions.

### D. Explainability Agent
*   **Role**: Translates structural statistics and evidence citations into natural text for CSMs.
*   **Logic**:
    1. Combines PCVL metrics and citations into an LLM prompt.
    2. If recommendation confidence is low ($< 0.5$), prepends a prominent warning: `"Low confidence — recommend human judgment over automation."`
    3. Restricts output to 2-4 sentences, citing sources (e.g., `"According to playbook kb_002..."`) while omitting basic profile fields already visible in the UI layout.

### E. Human-in-the-Loop Execution
*   **Role**: Pauses the graph before execute state, allowing CSMs to review and steer recommendations.
*   **Routing Logic**:
    *   `approve`: Proceeds to the memory update node, saving metadata, and terminates the graph.
    *   `reject`: Aborts the recommendation and terminates the graph.
    *   `edit`: Accepts user modifications to assumptions or profile data. The Planner routes state back to the **Reasoning Node** to recalculate scores, followed by **Explainability** to rewrite the rationale, before returning to review.

### F. Memory Update Agent
*   **Role**: Builds the dynamic historical profile of decisions to guide future recommendations.
*   **Logic**:
    1. Formulates a structured summary of the decision (e.g., *"For ApexLogistics, a Mid-Market customer with High churn risk, 'Schedule retention call' was approved by human reviewer."*).
    2. Writes this summary to a secondary ChromaDB collection (`interaction_history`) indexed by `case_id`.
    3. Exposes the `/memory_diff` endpoint to search this collection, showing CSMs how similar accounts were handled in past cases.

---

## 4. Key Design Decisions

### 1. Deterministic Planner vs. Autogenous LLM Routers
*   **Decision**: Use a programmatic Python function (`route_from_planner`) inside the Planner node to orchestrate SPOKE execution, rather than letting the LLM choose the next edge.
*   **Rationale**: Programmatic control ensures deterministic flow paths, eliminates execution loops, reduces LLM latency/tokens, and makes the system fully auditable.

### 2. State Persistence & Thread-Based Sessions
*   **Decision**: LangGraph compiled with `MemorySaver` in-memory checkpointer.
*   **Rationale**: Enables the API to interrupt execution right before the `execute` node, yielding control to the UI. The thread remains frozen in-memory until `/resume` is called, ensuring seamless state recovery.

### 3. Separation of Knowledge & Interaction Collections
*   **Decision**: Store core playbooks in a `knowledge_base` Chroma DB collection and human decisions in a separate `interaction_history` collection.
*   **Rationale**: Decoupling prevents historical execution data from diluting official corporate playbook retrieval, while still enabling the "Memory Diff" context comparison panel in the user interface.
*   
