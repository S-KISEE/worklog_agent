
import sys
import os

# Add current dir to path
sys.path.append(os.getcwd())

try:
    from my_agent.tools.query_validator import QueryValidatorTools
    
    print("Test: Verifying that joined fields in FIND are rejected.")
    validator = QueryValidatorTools()
    
    spec = {
        "collection": "worklogs",
        "operation": "find",
        "filter": {
            "user.email": "alice@example.com"
        },
        "projection": {"_id": 0, "tasks": 1}
    }
    
    result = validator.validate_query_spec(spec)
    
    print("--- Spec ---")
    print(spec)
    print("\n--- Validation Result ---")
    print(result)
    
    if not result.get("ok"):
        print("\n[SUCCESS] Validator correctly rejected 'user.email' in FIND.")
        if "Joined fields not supported" in result.get("message", ""):
            print("[SUCCESS] Error message contains the helper hint.")
        else:
            print("[i] Error message is standard (missing hint?).")
    else:
        print("\n[FAIL] Validator still ALLOWS 'user.email' in FIND (bad behavior).")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
