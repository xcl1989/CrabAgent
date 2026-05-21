---
name: python-debugger
description: "Systematically debug Python code using structured error analysis, logging inspection, and test-driven fixes"
---

# Python Debugger Skill

You are now operating with the Python Debugger skill. Follow this systematic approach when debugging Python code.

## Debugging Workflow

### Step 1: Reproduce the Error
- Run the failing code or test to confirm the error
- Capture the full traceback
- Identify the exact line and error type

### Step 2: Analyze the Error
- Read the error message carefully
- Check the types of variables involved
- Look at the call stack to understand the flow
- Use `read` to examine the relevant source files

### Step 3: Hypothesize
- Form a hypothesis about the root cause
- Consider common Python pitfalls:
  - Mutable default arguments
  - Off-by-one errors
  - Incorrect indentation
  - Type mismatches
  - Import circular dependencies
  - Missing `self` parameter
  - Incorrect exception handling

### Step 4: Verify and Fix
- Use `bash` to run targeted tests
- Use `edit` to apply the fix
- Run tests again to confirm the fix
- Check for regressions in related tests

### Step 5: Validate
- Run the full test suite if available
- Check edge cases
- Ensure no new warnings are introduced

## Tools Priority

1. `bash` - Run code and tests to reproduce/verify
2. `read` - Examine source files and tracebacks
3. `grep` - Search for patterns across the codebase
4. `edit` - Apply fixes

## Common Patterns

See [references/common-fixes.md](references/common-fixes.md) for a catalog of common Python bugs and their fixes.
