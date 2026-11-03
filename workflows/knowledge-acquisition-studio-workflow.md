# Knowledge Acquisition Studio Workflow

1. Receive goal.
2. Create/validate project manifest.
3. Orchestrator decomposes goal into tasks.
4. Execute highest-priority unblocked task.
5. Verify task.
6. On failure: diagnose, retry, re-verify.
7. On success: persist artifact and update status.
8. Select next unblocked task.
9. Continue until release criteria are satisfied.
10. Package stable workflow as the `knowledge-acquisition-studio` Skill.
