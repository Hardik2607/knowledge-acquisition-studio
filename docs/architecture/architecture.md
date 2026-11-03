# Architecture — Knowledge Acquisition Studio

```text
User Goal
   |
   v
Orchestrator
   |
   +--> Input / Validation
   +--> Specialist Agents
   +--> Research / Knowledge (when required)
   +--> Artifact Generation
   +--> QA / Verification
   |
   +--> PASS --> Status --> Next Task
   |
   +--> FAIL --> Diagnose --> Retry
```

The architecture is intentionally modular so individual agents can be replaced without redesigning the whole workflow.
