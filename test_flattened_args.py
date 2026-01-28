
import sys
import os

# Add current dir to path
sys.path.append(os.getcwd())

try:
    from my_agent.tools.query_validator import QueryValidatorTools
    
    print("Test: Verifying validator accepts FLATTENED args.")
    validator = QueryValidatorTools()
    
    # OLD WAY (still should work)
    print("\n[1] Testing nested 'spec' argument...")
    spec_nested = {
        "collection": "users",
        "operation": "find",
        "filter": {"fullname": "Alice"},
        "limit": 5
    }
    res_nested = validator.validate_query_spec(spec=spec_nested)
    if res_nested.get("ok"):
        print("  -> Nested spec worked!")
    else:
        print(f"  -> Nested spec FAILED: {res_nested}")

    # NEW WAY (flattened)
    print("\n[2] Testing FLATTENED arguments...")
    # Intentionally NOT proper join logic check here, just argument parsing check
    res_flat = validator.validate_query_spec(
        collection="users",
        operation="find",
        filter={"fullname": "Bob"},
        limit=10
    )
    
    if res_flat.get("ok"):
        print("  -> Flattened args worked!")
        # Check if it reconstructed spec correctly
        out_spec = res_flat.get("spec", {})
        if out_spec.get("collection") == "users" and out_spec.get("limit") == 10:
             print("  -> Internal spec construction verified.")
        else:
             print(f"  -> Internal spec MALFORMED: {out_spec}")
    else:
        print(f"  -> Flattened args FAILED: {res_flat}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
