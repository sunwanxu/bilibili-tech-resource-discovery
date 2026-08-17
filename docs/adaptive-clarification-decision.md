# Adaptive clarification decision

## Problem

The host Skill collected a fixed profile but could start discovery before resolving a technical
choice that changes the whole solution. “Build a gimbal”, for example, can lead to different actuator,
driver, control, and learning ecosystems. A fixed questionnaire cannot enumerate such choices across
technical domains.

## Open-source review

- **Rasa slots and forms — reference.** Dynamic required slots, ask-before-filling, validation, and
  controlled conversation state are useful patterns. The full framework is unnecessary because the
  host AI already owns the conversation and installing a dialogue server would harm portability.
  Sources: <https://rasa.com/docs/reference/primitives/slots/> and
  <https://rasa.com/docs/rasa-pro/concepts/dialogue-understanding/>
- **LangGraph interrupts — reference.** Pause/resume and durable human-in-the-loop state are useful
  for a future website service, but adding a graph runtime to this local Skill would duplicate host
  conversation state. Source: <https://github.com/langchain-ai/langgraph>

## Decision

Reference the established patterns without adding either dependency. The Skill performs a generic
decision-axis gate, asks the highest-impact unresolved question, validates it against existing facts,
and stores the answer in the existing `IntentProfile.constraints`. The deterministic query planner
now preserves those constraints. This is smaller, replaceable, Windows-friendly, and testable
offline.

The design intentionally avoids domain-specific route dictionaries. The host AI identifies candidate
routes from known constraints and, when needed, lightweight official/open-source research. Examples
exist only as behavioral evaluations.
