# JROS 0.5 Roadmap — Personality + Avatar + Streaming

**Status:** draft (2026-06-07) — proposal for operator review
**Pre-req:** 0.4.0 shipped (node architecture, voice loop fully bus-routed, Tracks A/B/C-skeleton landed)
**Target:** the agent gets a face and a personality the audience cares about

## The position

0.4 wired the spine.  0.5 gives it a soul and a face.

> **An agentic AI you can stream.**
> Structured personality (HEXACO + expression + domain weights) the
> agent USES on every turn — not just at wizard time.  A Live2D
> avatar driven by the bus the rest of JROS already speaks.  A
> stream mode operators can point OBS at and call a YouTube show.

The architecture decisions from 0.4 carry over verbatim:

* Brain stays one process; new capabilities are nodes.
* Tools = networking shims; nodes = execution.
* Universal interfaces in the library; per-instance specifics
  at the operator's instance dir.
* msgspec for transport schemas; Pydantic for config + manifest.
* Make it exist first, then make it good.

## The single biggest decision

**0.5 vendors working pipelines from
[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)
with attribution; we OWN the resulting code.**

What "vendor" means:

* We copy specific files (Live2D loader + lip-sync algorithm + idle
  animations + Cubism SDK glue) into our repo.
* Once in tree, the code is ours — we modify freely, test under our
  discipline, decide what to backport from upstream.
* Open-LLM-VTuber gets credit in
  `dev_docs/library_review/open_llm_vtuber.md`, in `README.md`'s
  acknowledgments, and inline at the file headers of vendored code.
* We do NOT depend on their package, submodule them, or sit on
  their release schedule.

What we write ourselves:

* The AvatarNode (Python; must satisfy JROS bus contract).
* The `/act/avatar_state` topic schema (msgspec.Struct, our SSOT).
* The WebSocket server (lightweight Flask/aiohttp; our tests).
* Integration with `/sense/spoken`, `/sense/transcript`, the agent's
  tool surface.
* Persona-to-avatar mapping (HEXACO + expression sliders →
  default expressions for the model).

Same pattern as `dev_tools/audio_smoke/voice_assistant_persistent.py`
— we vendored the operator's earlier voice loop as a working
reference, modified it freely, kept attribution in the file.

---

## Architecture additions

### New topic — `/act/avatar_state`

```python
class AvatarState(TopicMessage):
    """Brain → avatar node: set the avatar's emotional + spatial
    state.  Published by the agent (via a new `set_avatar_state`
    tool) AND automatically by the voice loop on state transitions
    ('listening' when STT opens, 'thinking' during agent decode,
    'speaking' when TTS fires)."""
    topic: Literal["/act/avatar_state"] = ACT_AVATAR_STATE
    emotion: str = "neutral"
    # "neutral" | "happy" | "sad" | "focused" |
    # "thinking" | "surprised" | "speaking" | "listening"
    look_at_x: float = 0.0      # -1.0 (left) … 1.0 (right)
    look_at_y: float = 0.0      # -1.0 (down) … 1.0 (up)
    blink: bool | None = None   # None = automatic; True/False = forced
    duration_ms: int = 0        # 0 = hold until next message
```

The agent's tool surface gains:

```python
set_avatar_state(emotion: str = "neutral",
                 look_at_x: float = 0.0,
                 look_at_y: float = 0.0)
```

Same "tool publishes, node executes" contract as
`text_to_speech` post-0.4.

### Identity schema promoted from free-text to structured

`config.identity.personality` (a single 2048-char free-text field
today) gains a structured sibling `config.identity.personality_v2`:

```yaml
identity:
  display_name: "Lilith"
  voice_id: "af_heart"

  personality_v2:
    schema: persona/v2
    hexaco:
      openness: 0.50
      conscientiousness: 0.50
      extraversion: 0.40
      agreeableness: 0.50
      neuroticism: 0.55
      honesty_humility: 0.85
    expression:
      sarcasm: 0.45
      warmth: 0.50
      verbosity: 0.50
      formality: 0.50
      directness: 0.80
      humor: 0.30
      empathy: 0.40
      aggression: 0.30
    domains:
      science: 0.85
      philosophy: 0.75
      technology: 0.90
    speech_patterns:
      - "Speaks with quiet precision — never wastes words"
      - "Asks incisive questions rather than making assumptions"
      - "Does not soften hard truths but delivers them without cruelty"
```

The composed system prompt block adds (when `personality_v2` is set):

```
## How I express myself (calibrated)

  Sarcasm:     low-medium       Warmth:    medium
  Directness:  HIGH             Formality: medium
  Verbosity:   medium           Humor:     low

## Speech patterns

  - Speaks with quiet precision — never wastes words.
  - …
```

Backward-compat: instances with only the v1 free-text field continue
to work unchanged.

---

## Tracks

### Track A — Foundations (audits + 0.5.0 prep)

Lock the design decisions before writing code.

* **A.1** `dev_docs/library_review/open_llm_vtuber.md` —
  audit of their structure.  What we'd vendor (Live2D loader,
  lip-sync, idle animations), what we wouldn't (their LLM/STT/TTS
  stack), licence notes (Open-LLM-VTuber MIT; Live2D Cubism SDK
  per-model + commercial-use distinctions), specific files to copy.
* **A.2** `dev_docs/library_review/lilith_personality.md` —
  audit of `/Users/jonathanjenkins/GITHUB/Lilith-AI/archive/`.  Maps
  every personality field Lilith 0.2.2 had to what JROS would do
  with it (system prompt composition, avatar default expressions,
  voice tuning, skill bundle hints).
* **A.3** First-class Lilith preset at `jaeger_os/personas/lilith.yaml`
  alongside `jarvis.yaml`.  Uses the v2 structured personality.
  No code path yet uses v2 — just the data is there.

### Track B — Personality (the soul)

Promote personality from one free-text field to a structured model
the agent actually USES on every turn.

* **B.1** `Persona` schema (Pydantic, in
  `core/instance/schemas.py`).  HEXACO + expression + domains +
  speech_patterns.  Optional field on `Identity`.
* **B.2** `core/prompts/persona_compose.py` — turns the structured
  data into a system-prompt block.  Pure function, unit-tested.
* **B.3** Compose into the system prompt every turn (the existing
  `assemble_prompt` flow gains a conditional block).
* **B.4** Wizard prefill — when an operator picks a preset that
  has `personality_v2`, the wizard writes it.  v1 free-text path
  continues to work for legacy instances.
* **B.5** Persona-driven voice tuning — high `humor` could nudge
  Kokoro toward a more playful voice; high `formality` toward a
  measured one.  (Stretch — only if Kokoro's parameter space
  supports it.)

### Track C — Avatar node (the face)

The Live2D-driven avatar.  Same per-subsystem package shape as
`jaeger_os/nodes/{tts,stt,vision}/`.

* **C.1** `jaeger_os/nodes/avatar/` skeleton.  AvatarAdapter
  Protocol + AvatarNode skeleton with no rendering, just lifecycle
  + subscriptions.  Tests with a mock adapter.
* **C.2** `WebRendererAdapter` — Flask + WebSocket server that
  serves a placeholder HTML page (no Live2D yet, just a visible
  test rectangle).  `./launch --stream` opens the page.
* **C.3** Vendor Live2D rendering pipeline from Open-LLM-VTuber.
  Copy specific files into `jaeger_os/nodes/avatar/web/` with
  attribution.  Replace their model-loader hooks with our
  WebSocket protocol.
* **C.4** Lip sync — `/sense/spoken` events drive mouth
  parameters.  Use Open-LLM-VTuber's amplitude-to-mouth-shape
  algorithm as the reference, port to our event flow.
* **C.5** Expression mapping — `/act/avatar_state.emotion` →
  Cubism expression file.  Start with 5 emotions: neutral, happy,
  sad, focused, thinking.
* **C.6** Idle animations — breathing, blinking, micro-movements
  so the model doesn't feel static.  Vendor from Open-LLM-VTuber.
* **C.7** `set_avatar_state` agent tool.  Publishes
  `/act/avatar_state`; respects permission tier.
* **C.8** Voice-loop auto-publishes — `/act/avatar_state` switches
  to "listening" when STT opens follow-up, "thinking" during agent
  decode, "speaking" while TTS plays.  Same node-shape: voice loop
  is a tool publishing, avatar node executes.

### Track D — Streaming mode

The OBS-capturable production surface.

* **D.1** `./launch --stream` boot mode.  Voice auto-on; avatar
  window auto-launched; TUI minimised (background mode); status
  bar shows on-air indicator.
* **D.2** Stream-specific config block in instance config:

  ```yaml
  stream:
    enabled: false
    avatar_window_url: "http://127.0.0.1:8765"
    show_stt_overlay: false   # for debugging
    show_thinking_indicator: true
  ```
* **D.3** Avatar HTML page becomes OBS-friendly — transparent
  background; fixed window size operator can pick (default
  1280×720).
* **D.4** Stream watchdog — if the avatar window crashes (rare
  but possible during browser GC), the node restarts it.  Same
  pattern Track D's supervisor-port from 0.4 followups will use.

### Track E — Hardware avatar (long-term, deferred to 0.5.x)

The avatar that runs ON the robot's screen, not just OBS.

* **E.1** Reuse the same `AvatarNode` + WebSocket protocol; the
  renderer just runs on a Jetson with an attached display.
* **E.2** Camera-driven eye tracking — vision node observes user,
  publishes `/sense/user_position`; avatar's `look_at_x/y`
  follows.

This is post-0.5.0; mentioned here so the architecture in Tracks
B + C doesn't paint itself into a corner.

**Operator-locked (2026-06-07):** each robot is a standalone
agent with ONE persona.  We deliberately don't design for
multi-persona switching within a single robot — Lilith's robot
is Lilith.  Jarvis's robot is Jarvis.  This keeps the avatar /
persona / voice / skill tuning cohesive per instance and avoids
the complexity tax of persona-swap UX.

### Track F — Node supervision + runtime (early in 0.5)

Operator-locked 2026-06-07: **bake the supervision framework in
NOW while we have ~6 nodes, not later when we have 20.**  Every
new node that lands AFTER this track inherits the pattern for
free; retrofitting it across a fleet is painful.

Previously deferred as Track D in the 0.4 roadmap.  Promoting to
a 0.5 Track because the cost-of-delay is real: avatar (Track C)
and persona hot-reload (Track B) both need supervision to be safe
on a live YouTube stream.

* **F.1** `dev_docs/library_review/mochi_demo.md` audit (with the
  Mochi reference 2026-06-08) explicitly catalogues supervision /
  runtime / health patterns Mochi already has — operator believes
  it does.  Anything reusable informs F.3.  Hermes's
  `supervisor.py` is also preserved at
  `dev_docs/library_review/hermes_supervisor.py` as a fallback
  reference if Mochi doesn't cover the supervisor piece.

* **F.2** New topic `/sense/health` + `NodeHealth` schema (msgspec.
  Struct).  Every node publishes a heartbeat each tick.  Schema:

  ```python
  class NodeHealth(TopicMessage):
      topic: Literal["/sense/health"] = SENSE_HEALTH
      node: str = ""
      state: str = "running"        # NodeState.value
      uptime_s: float = 0.0
      last_error: str | None = None
      extras: dict = msgspec.field(default_factory=dict)
  ```

  `Node.health()` already returns this shape; we just need the
  bus publish + a subscriber on the brain side.

* **F.3** `jaeger_os/supervisor.py` — port from the Hermes
  reference (or vendor patterns from Mochi if it has them),
  adapted for the Node base class.  Wraps a node thread /
  subprocess with:
  - exponential backoff on crash (doubles per crash, caps at 60s)
  - good-run reset (back to base delay after a long clean run)
  - crash log appended to `<instance>/run/supervisor.crash.log`
  - max-restarts gate (default unbounded; configurable)

* **F.4** Promote `runtime.ensure_*_node` factories from the 0.4
  patch round (`146b960`) to the canonical node-spawn path.
  Supervisor wraps the factory.  Operator never starts a raw
  node; they get a supervised one.

* **F.5** `/sense/health` subscription in the brain.  Surface
  missing heartbeats as "node X went dark":
  - `./launch --health` already exists; extend it with live
    node status
  - new `/nodes` TUI slash command lists active nodes + state +
    last seen
  - operator notifications when a node restarts (TUI status bar
    indicator)

* **F.6** Backpressure policy per-topic.  ZMQ HWM + InProcBus
  overflow path already exist; this track documents per-topic
  defaults:
  - audio frames: drop oldest (latency over completeness)
  - motor commands: drop oldest (most recent intent wins)
  - LLM tool dispatches: never drop (queue without limit)
  - health heartbeats: drop newest (one missed beat OK)

**Why F is early-0.5, not 0.5.x:**

1. Track C (avatar) ships in 0.5 → without supervision a renderer
   crash silently breaks the YouTube stream.
2. Track B (per-turn persona composition) ships in 0.5 → a
   compose bug becomes a per-turn crash; supervisor + health
   makes that recoverable instead of catastrophic.
3. Mochi-style face needs ~50 Hz lip-sync events on
   `/sense/tts_chunk` → backpressure policy matters; without
   it, a slow renderer wedges the bus.

Estimated scope: ~400 lines new code, ~150 lines tests.  Smaller
than Track B + C combined; big leverage.

---

## Milestones

### 0.5.0 — must-have

* Track A.1 + A.2 + A.3 (audits + Lilith preset data)
* **Track F.1 + F.2 + F.3 + F.4 + F.5 — node supervision +
  runtime framework lands EARLY in 0.5 before Tracks B + C add
  more nodes / per-turn complexity.**  Audit Mochi for existing
  patterns first; build on what's there.
* Track B.1 + B.2 + B.3 (structured personality affects the system
  prompt every turn)
* Track C.1 + C.2 + C.3 + C.4 + C.5 + C.6 + C.7 (avatar visible
  + breathes + lip-syncs + responds to `set_avatar_state`)
* Track C.8 (voice loop drives avatar state)
* Track D.1 + D.3 (`./launch --stream` opens the avatar window;
  OBS-friendly)
* Lilith persona working: HEXACO + expression composed into her
  system prompt; Live2D model showing on screen with her base
  expression; lip syncs when she speaks; agent can call
  `set_avatar_state("focused")` and the model responds.

**Verification gate:** point OBS at the avatar window, start
voice mode, have a conversation.  The avatar moves its mouth in
time with replies and changes expression when the agent calls
`set_avatar_state`.

### 0.5.1 → 0.5.4 — followups (deferred)

* B.4 wizard prefill for v2 personas
* B.5 persona-driven voice tuning
* C.x polish (more expressions, smoother lip sync, better idle)
* D.2 stream config block, D.4 stream watchdog
* Live YouTube chat → agent bridge (a new node: `youtube_chat`
  subscribes to chat events, publishes as if STT had transcribed
  them).  Optional but high-value once the rest works.
* E.1 → E.3 hardware avatar (Jetson display)

---

## Open questions

1. **Live2D model for Lilith.**  Community model for MVP
   validation, or commission/build one before 0.5.0 ships?
   Affects Track A.1 licence audit.

2. **Browser window vs. pywebview.**  For `./launch --stream`,
   should the avatar window be a real native window JROS owns
   (pywebview), or just a URL operators point their own browser
   at?  Native window feels more product-y; URL is simpler.

3. **Persona v1 → v2 migration.**  When does v1 free-text get
   deprecated?  Probably never — keep both forever, v1 is
   simpler for operators who just want "concise + helpful".
   But the wizard's default at 0.6+ should be v2.

4. **`set_avatar_state` permission tier.**  Pure UI control, no
   external effect.  Probably READ_LOCAL.  But could surprise
   an operator if the agent flips expressions during serious
   debugging.  Worth a `display.avatar_agent_control: bool` flag.

5. **Lip sync data source.**  `/sense/spoken` is the ack AFTER
   audio plays — too late for lip sync.  We probably need
   `/act/audio_out` (raw speaker frames) for amplitude analysis,
   OR a new `/sense/tts_chunk` published by the TTS node as
   each chunk fires.  The latter is cleaner.

---

## Library inventory queue

| Library | Status |
|---|---|
| **Open-LLM-VTuber** | A.1 audit pending — vendor working pipelines |
| **Lilith-AI archive** | A.2 audit pending — promote personality data |
| **Live2D Cubism Web SDK** | dependency for the renderer; licence audit during A.1 |
| **VoiceLLM** | absorbed at 0.4; operator may delete now |
| **Hermes** | absorbed at 0.4; supervisor preserved; operator may delete now |
| **JP01_Firmware** | informed Track C universal interfaces at 0.4; stays as reference for Track E hardware avatar |

---

## Position statement update (for `README.md`)

The 0.4 README pitch was:

> JROS = ROS + Agentic AI + Mac-first local hardware.

0.5 extends this without replacing it:

> **An agentic AI you can stream.**
> Local Gemma brain.  Live2D avatar.  Structured personality the
> agent USES every turn.  Voice-mode that feels like a
> conversation, not a chat box.  OBS-capturable out of the box.

The "stream" framing fits the YouTube channel goal without
abandoning the embodied-robot future — same code, same avatar,
just different output devices.
