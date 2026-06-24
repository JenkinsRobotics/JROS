# JROS — full-stack pipeline infographics

End-to-end layouts of everything JROS touches: the sense → brain → act loop,
the avatar systems, voice in/out, hardware, and user input. Diagrams are
**Mermaid in markdown** — they render as visuals in GitHub / VS Code / the
[mermaid.live](https://mermaid.live) editor, and the source stays diffable.
(Any diagram can also be exported to PNG/SVG if a flat image is wanted.)

**Status legend:** ✅ built · 🟡 partial / in progress · ◇ planned (to build)

---

## Master loop — end to end

```mermaid
flowchart TB
    user(["User — voice · keyboard · touch"])

    subgraph SENSE["SENSE · input"]
      mic["mic"] --> audio["audio_session node<br/>VAD + dual-Whisper STT ✅"]
      cam["camera"] --> vision["vision node 🟡"]
      touch["touch / keys"] --> ui["TUI / Studio input ✅"]
    end

    subgraph BRAIN["BRAIN"]
      agent["agent turn loop ✅<br/>LLM + tools<br/>active-character persona"]
      trace["trace recorder ✅<br/>logs/trace.jsonl"]
    end

    subgraph ACT["ACT · output nodes"]
      tts["tts node — Kokoro ✅"]
      anim["animation node ✅<br/>2D adapters + MScript"]
      media["media node 🟡"]
      motor["motor node 🟡"]
      light["light node 🟡"]
    end

    subgraph RENDER["RENDER · body"]
      spk["speaker ✅"]
      bridge["FrameBridge · WebSocket ✅"]
      avatar2d["2D avatar — Swift app /<br/>avatar_player popup ✅"]
      avatar3d["3D avatar ◇"]
      mediawin["media_player popup 🟡"]
      hw["hardware — servos / LEDs ◇"]
    end

    user --> mic & cam & touch
    audio -->|/sense/transcript| agent
    vision -->|/sense/vision_analysis| agent
    ui -->|/act/chat| agent
    agent -->|/act/speech| tts
    agent -->|/act/animation| anim
    agent -->|/act/media| media
    agent -->|/act/motion| motor
    agent -->|/act/light| light
    tts --> spk
    tts -->|/sense/tts_chunk · amplitude → lip-sync ✅| anim
    anim -->|/sense/avatar_frame| bridge
    bridge --> avatar2d
    bridge -.-> avatar3d
    media -->|/sense/media_frame| mediawin
    motor --> hw
    light --> hw
    agent -.->|/sense/trace_step| trace

    classDef built fill:#15402b,stroke:#3fae6f,color:#eafff2;
    classDef partial fill:#473a14,stroke:#c9a13b,color:#fff7e0;
    classDef plan fill:#3a1530,stroke:#a64fa6,color:#ffe9fb,stroke-dasharray:5 3;
    class audio,ui,agent,trace,tts,anim,spk,bridge,avatar2d built;
    class vision,media,motor,light,mediawin partial;
    class avatar3d,hw plan;
```

Everything rides the **transport bus** (`InProcBus` today, `ZmqBus` for
multi-machine). Topics: `/sense/*` (inputs), `/act/*` (commands).

---

## Pipelines (each gets its own detail diagram)

| Pipeline | Status | Detail diagram |
|---|---|---|
| Voice in · ASR (mic → VAD → STT → transcript) | ✅ built | `voice_in_asr.md` ◇ |
| STT → LLM → TTS (the conversation loop) | ✅ built | `stt_llm_tts.md` ◇ |
| 2D avatar (animation node → frames → renderer) | ✅ built | `avatar_2d.md` ◇ |
| Lip-sync (`/sense/tts_chunk` amplitude → mouth) | ✅ built | `lip_sync.md` ◇ |
| 3D avatar | ◇ planned | `avatar_3d.md` ◇ |
| Media (media node → frames → player) | 🟡 in progress | `media.md` ◇ |
| Hardware integration (motor / light / sensors) | 🟡 partial | `hardware.md` ◇ |
| User input (voice / keyboard / Studio / touch) | ✅ built | `user_input.md` ◇ |
| Observability (trace → baseline) | ✅ built | `observability.md` ◇ |

◇ = diagram not written yet. The statuses above are a first-pass read; each
detail diagram verifies the exact wiring against the code before it's marked.
