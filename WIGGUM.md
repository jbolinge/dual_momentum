# Ralph Wiggum Configuration

## Completion Promise

The completion phrase for this project is: `TASK COMPLETE`

When the Ralph loop detects `<promise>TASK COMPLETE</promise>` in the output, it will stop iterating.

## Success Criteria

Before outputting the completion promise, verify:

1. **All tests pass**: `uv run pytest` exits with code 0
2. **CLI runs successfully**: `uv run dm` produces output without errors
3. **Output is correct**: Shows period returns, weighted returns, and winner

## How to Use

Start the Ralph loop with:

```bash
/ralph-loop "$(cat PROMPT.md)" --completion-promise "TASK COMPLETE" --max-iterations 25
```

Or manually run Claude Code with the prompt:

```bash
cat PROMPT.md | claude-code --continue
```

## Iteration Strategy

Each iteration should:

1. Run `uv run pytest -v` to check test status
2. If tests fail, fix the failing code
3. If tests pass, verify CLI works with `uv run dm`
4. If anything is missing, write tests first, then implement
5. When everything works, output the completion promise

## Max Iterations

Recommended: 25 iterations maximum. If not complete by then, review the approach.
