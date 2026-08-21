from typing import TypedDict, Any, List, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

# State Schema contracts
class PulseState(TypedDict):
    case_id: str
    raw_input: str                  # raw CRM note / transcript text
    customer_profile: dict          # structured output of Ingestion Agent
    assumptions: dict                # flagged assumptions Ingestion Agent had to infer (e.g. contract_type)
    retrieved_evidence: List[dict]   # chunks from Knowledge Retrieval Agent, each {text, source, score}
    recommendation: dict             # {action, propensity, context, value, levers, priority, confidence}
    explanation: str                 # human-readable rationale from Explainability Agent (teammate C)
    plan_trace: List[str]            # Planner's logged routing decisions + reasoning
    status: str                      # "pending_review" | "approved" | "edited" | "rejected" | "executed"
    human_decision: Optional[dict]   # set by the API on resume

# Import node functions and routing helper
from agents.planner import planner_node, route_from_planner
from agents.ingestion import ingestion_node
from agents.retrieval import retrieval_node
from agents.reasoning import reasoning_node
from agents.explainability import explainability_node
from agents.memory_update import memory_update_node

def execute_node(state: PulseState) -> Any:
    print("--- RUNNING EXECUTE NODE (HITL) ---")
    decision_data = state.get("human_decision")
    if not decision_data:
        print("Warning: Execute node entered without human_decision.")
        return {"status": "pending_review"}
        
    decision = decision_data.get("decision")
    edit_payload = decision_data.get("edit_payload")
    
    plan_trace = list(state.get("plan_trace", []))
    
    if decision == "approve":
        print(f"Action Approved! Executing recommendation: {state.get('recommendation')}")
        msg = "Execute: Action approved by human. Proceeding to memory update."
        plan_trace.append(msg)
        return Command(
            goto="memory_update",
            update={
                "status": "approved",
                "plan_trace": plan_trace
            }
        )
    elif decision == "reject":
        print(f"Action Rejected! Recommendation: {state.get('recommendation')}")
        msg = "Execute: Action rejected by human. Ending process."
        plan_trace.append(msg)
        return Command(
            goto=END,
            update={
                "status": "rejected",
                "plan_trace": plan_trace
            }
        )
    elif decision == "edit":
        print(f"Action Edited! Payload: {edit_payload}")
        # Apply the edit payload to customer_profile and assumptions
        cp = dict(state.get("customer_profile", {}))
        ass = dict(state.get("assumptions", {}))
        
        if edit_payload:
            for key, val in edit_payload.items():
                cp[key] = val
                # Resolve the assumption for this key if it exists
                if key in ass:
                    del ass[key]
                    
        msg = f"Execute: Assumptions edited by human ({list(edit_payload.keys()) if edit_payload else []}). Re-routing to Reasoning."
        plan_trace.append(msg)
        return Command(
            goto="reasoning",
            update={
                "customer_profile": cp,
                "assumptions": ass,
                "status": "edited",
                "plan_trace": plan_trace
            }
        )
        
    return {"status": "pending_review"}

# Build StateGraph
builder = StateGraph(PulseState)

# Register nodes
builder.add_node("planner", planner_node)
builder.add_node("ingestion", ingestion_node)
builder.add_node("retrieval", retrieval_node)
builder.add_node("reasoning", reasoning_node)
builder.add_node("explainability", explainability_node)
builder.add_node("memory_update", memory_update_node)
builder.add_node("execute", execute_node)

# Set up edges
builder.add_edge(START, "planner")

# Conditional edge from central planner node
builder.add_conditional_edges("planner", route_from_planner, {
    "ingestion": "ingestion",
    "retrieval": "retrieval",
    "reasoning": "reasoning",
    "explainability": "explainability",
    "execute": "execute"
})

# Spokes return back to central planner node
builder.add_edge("ingestion", "planner")
builder.add_edge("retrieval", "planner")
builder.add_edge("reasoning", "planner")
builder.add_edge("explainability", "planner")

# Memory update terminal edge
builder.add_edge("memory_update", END)

# In-memory checkpointer for manual execution thread persistence
memory = MemorySaver()

# Compile graph with static interrupt before the execution node
graph = builder.compile(checkpointer=memory, interrupt_before=["execute"])
