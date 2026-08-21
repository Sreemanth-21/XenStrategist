import sys
import os
import uuid
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.graph import graph
from langgraph.types import Command
#agents done
app = FastAPI(
    title="Pulse Orchestration API",
    description="FastAPI backend for Pulse Next Best Action Customer Success platform"
)

class ProcessRequest(BaseModel):
    case_id: Optional[str] = None
    raw_input: str

class ResumeRequest(BaseModel):
    thread_id: str
    decision: str          # "approve" | "edit" | "reject"
    edit_payload: Optional[Dict[str, Any]] = None

@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.post("/process")
def process_case(request: ProcessRequest):
    """
    Starts a new case. Runs Planner → Ingestion → Retrieval → Reasoning → Explainability,
    then pauses at the execute node awaiting human decision.
    """
    thread_id = request.case_id or f"case-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "case_id":           thread_id,
        "raw_input":         request.raw_input,
        "customer_profile":  {},
        "assumptions":       {},
        "retrieved_evidence":[],
        "recommendation":    {},
        "explanation":       "",
        "plan_trace":        [],
        "status":            "new",
        "human_decision":    None,
    }

    try:
        list(graph.stream(initial_state, config))
        state = graph.get_state(config)
        state_values = dict(state.values)

        if "execute" in (state.next or []):
            state_values["status"] = "pending_review"
            graph.update_state(config, {"status": "pending_review"}, as_node="planner")

        return {
            "thread_id":         thread_id,
            "status":            state_values.get("status"),
            "customer_profile":  state_values.get("customer_profile"),
            "assumptions":       state_values.get("assumptions"),
            "recommendation":    state_values.get("recommendation"),
            "explanation":       state_values.get("explanation"),
            "plan_trace":        state_values.get("plan_trace"),
            "retrieved_evidence":state_values.get("retrieved_evidence"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting case: {str(e)}")


@app.post("/resume")
def resume_case(request: ResumeRequest):
    """
    Resumes a paused case. Supports approve, reject, or edit (triggers re-reasoning).
    """
    if request.decision not in ["approve", "edit", "reject"]:
        raise HTTPException(status_code=400, detail="Decision must be 'approve', 'edit', or 'reject'")

    config = {"configurable": {"thread_id": request.thread_id}}
    state_before = graph.get_state(config)

    if not state_before.next or "execute" not in state_before.next:
        raise HTTPException(
            status_code=400,
            detail=f"Thread '{request.thread_id}' is not awaiting a decision. next={state_before.next}"
        )

    original_recommendation = state_before.values.get("recommendation")

    decision_payload = {
        "decision":     request.decision,
        "edit_payload": request.edit_payload,
    }

    try:
        graph.update_state(config, {"human_decision": decision_payload}, as_node="planner")
        list(graph.stream(Command(resume=decision_payload), config))

        state_after  = graph.get_state(config)
        state_values = state_after.values

        response = {
            "thread_id":        request.thread_id,
            "status":           state_values.get("status"),
            "customer_profile": state_values.get("customer_profile"),
            "assumptions":      state_values.get("assumptions"),
            "explanation":      state_values.get("explanation"),
            "plan_trace":       state_values.get("plan_trace"),
        }

        if request.decision == "edit":
            response["original_recommendation"]  = original_recommendation
            response["corrected_recommendation"] = state_values.get("recommendation")
        else:
            response["recommendation"] = state_values.get("recommendation")

        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error resuming case: {str(e)}")


@app.get("/memory_diff")
def memory_diff(company_name: str = Query(..., description="Company name to find similar past decisions")):
    """
    Queries interaction_history Chroma collection for past decisions
    similar to the current company/case, to power the Memory Diff panel.
    Uses the find_similar_past_cases function from the Memory Update Agent.
    """
    try:
        from agents.memory_update import find_similar_past_cases
        profile = {"company_name": company_name}
        past_cases = find_similar_past_cases(profile, k=3)

        output = []
        for case in past_cases:
            output.append({
                "company_name":   company_name,
                "action":         case.get("action", "—"),
                "human_decision": case.get("decision", "—"),
                "summary":        case.get("summary_text", "—"),
                "timestamp":      case.get("timestamp", "—"),
            })
        return {"results": output}
    except Exception as e:
        return {"results": [], "error": str(e)}
