import os
import sys

# Ensure the parent directory is in sys.path so agent can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import uuid
import pprint
from agents.graph import graph

def main():
    # Parse command line argument for scenario filename (defaults to scenario_1_churn.json)
    filename = "scenario_1_churn.json"
    if len(sys.argv) > 1:
        filename = sys.argv[1]
        
    # Resolve workspace root and scenario file path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_root = os.path.dirname(script_dir)
    scenario_path = os.path.join(workspace_root, "data", "scenarios", filename)
    
    # Try alternate path lookup if not found directly
    if not os.path.exists(scenario_path):
        if os.path.exists(filename):
            scenario_path = filename
        else:
            print(f"Error: Scenario file not found at {scenario_path}", file=sys.stderr)
            scenarios_dir = os.path.join(workspace_root, "data", "scenarios")
            if os.path.exists(scenarios_dir):
                print(f"Available scenarios: {os.listdir(scenarios_dir)}", file=sys.stderr)
            sys.exit(1)
            
    print(f"Loading scenario data from: {scenario_path}")
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)
        
    # Build initial PulseState
    initial_state = {
        "case_id": scenario_data.get("scenario_id", "case_unknown"),
        "raw_input": scenario_data.get("raw_text", ""),
        "customer_profile": {},
        "assumptions": {},
        "retrieved_evidence": [],
        "recommendation": {},
        "explanation": "",
        "plan_trace": [],
        "status": "pending",
        "human_decision": None
    }
    
    # Thread config for LangGraph memory checkpointer using case_id
    case_id = scenario_data.get("scenario_id", "case_unknown")
    config = {"configurable": {"thread_id": case_id}}
    
    print(f"Invoking Pulse LangGraph. thread_id: {case_id}")
    
    try:
        # Run graph until it hits interrupt_before=["execute"]
        final_state = graph.invoke(initial_state, config)
        print("\n=== GRAPH PAUSED (INTERRUPTED BEFORE EXECUTE) ===\n")
        
        print("=== RECOMMENDATION ===")
        pprint.pprint(final_state.get("recommendation", {}))
        
        print("\n=== RETRIEVED EVIDENCE ===")
        pprint.pprint(final_state.get("retrieved_evidence", []))
        
        print("\n=== PLAN TRACE ===")
        for step in final_state.get("plan_trace", []):
            print(f"  * {step}")
            
        print("\n=== STATUS ===")
        print(final_state.get("status"))
        
    except Exception as e:
        print(f"Execution Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
