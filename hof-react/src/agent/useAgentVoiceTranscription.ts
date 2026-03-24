"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type AgentVoiceTranscriptionState =
  | "idle"
  /** Browser permission / `getUserMedia` in progress */
  | "preparing_mic"
  /** WebRTC offer/answer and peer setup in progress */
  | "linking_session"
  /** Data channel open; audio is sent for transcription */
  | "listening"
  /** Mic stopped; waiting for server to finish the last utterance */
  | "finalizing"
  | "unsupported";

export type UseAgentVoiceTranscriptionOptions = {
  sessionPath: string;
  language: string;
  transcriptionPrompt: string;
};

function buildAuthHeaders(): HeadersInit {
  const token =
    typeof localStorage !== "undefined"
      ? localStorage.getItem("hof_token")
      : null;
  return {
    "Content-Type": "application/sdp",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

/**
 * Streaming speech-to-text via OpenAI Realtime API (WebRTC).
 * POSTs SDP to {@link UseAgentVoiceTranscriptionOptions.sessionPath}; transcription
 * deltas arrive on the peer data channel.
 */
export function useAgentVoiceTranscription(
  options: UseAgentVoiceTranscriptionOptions,
): {
  state: AgentVoiceTranscriptionState;
  interim: string;
  error: string | null;
  clearError: () => void;
  start: (onTranscript: (text: string) => void) => void;
  stop: (opts?: { flushPartial?: (text: string) => void }) => void;
} {
  const { sessionPath, language, transcriptionPrompt } = options;
  const optionsRef = useRef(options);
  optionsRef.current = { sessionPath, language, transcriptionPrompt };

  const [state, setState] = useState<AgentVoiceTranscriptionState>(() => {
    if (typeof window === "undefined") return "idle";
    if (!navigator.mediaDevices?.getUserMedia) return "unsupported";
    return "idle";
  });
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);

  const activeRef = useRef(false);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const callbackRef = useRef<((text: string) => void) | null>(null);
  const interimRef = useRef("");
  const listeningReachedRef = useRef(false);
  const drainingRef = useRef(false);
  const drainTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingFlushRef = useRef<((text: string) => void) | undefined>(
    undefined,
  );
  const stopInProgressRef = useRef(false);

  useEffect(() => {
    if (typeof navigator !== "undefined" && !navigator.mediaDevices?.getUserMedia) {
      setState("unsupported");
    }
  }, []);

  const finishDrainAndClose = useCallback(() => {
    if (drainTimerRef.current) {
      clearTimeout(drainTimerRef.current);
      drainTimerRef.current = null;
    }
    drainingRef.current = false;
    const flush = pendingFlushRef.current;
    pendingFlushRef.current = undefined;
    const partial = interimRef.current.trim();
    if (partial && flush) {
      flush(partial.endsWith(" ") ? partial : `${partial} `);
    }
    interimRef.current = "";
    setInterim("");
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    dataChannelRef.current = null;
    listeningReachedRef.current = false;
    activeRef.current = false;
    stopInProgressRef.current = false;
    const pc = pcRef.current;
    pcRef.current = null;
    pc?.close();
    setState("idle");
  }, []);

  const cleanup = useCallback(() => {
    if (drainTimerRef.current) {
      clearTimeout(drainTimerRef.current);
      drainTimerRef.current = null;
    }
    drainingRef.current = false;
    pendingFlushRef.current = undefined;
    stopInProgressRef.current = false;
    listeningReachedRef.current = false;
    activeRef.current = false;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    dataChannelRef.current = null;
    const pc = pcRef.current;
    pcRef.current = null;
    pc?.close();
    interimRef.current = "";
    setInterim("");
    setState("idle");
  }, []);

  const stop = useCallback(
    (opts?: { flushPartial?: (text: string) => void }) => {
      if (stopInProgressRef.current) {
        return;
      }
      if (!activeRef.current || !pcRef.current) {
        cleanup();
        return;
      }

      stopInProgressRef.current = true;
      pendingFlushRef.current = opts?.flushPartial;

      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;

      const dc = dataChannelRef.current;
      const canCommit =
        dc &&
        dc.readyState === "open" &&
        listeningReachedRef.current;

      if (canCommit) {
        drainingRef.current = true;
        try {
          dc.send(JSON.stringify({ type: "input_audio_buffer.commit" }));
        } catch {
          /* ignore */
        }
        setState("finalizing");
        drainTimerRef.current = setTimeout(() => {
          drainTimerRef.current = null;
          finishDrainAndClose();
        }, 2800);
      } else {
        finishDrainAndClose();
      }
    },
    [cleanup, finishDrainAndClose],
  );

  const clearError = useCallback(() => setError(null), []);

  const start = useCallback(
    (onTranscript: (text: string) => void) => {
      if (activeRef.current) cleanup();

      callbackRef.current = onTranscript;
      activeRef.current = true;
      setError(null);
      setState("preparing_mic");

      void (async () => {
        const o = optionsRef.current;

        let stream: MediaStream;
        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch {
          setState("idle");
          activeRef.current = false;
          setError("Microphone access denied.");
          return;
        }
        if (!activeRef.current) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        setState("linking_session");

        const pc = new RTCPeerConnection();
        pcRef.current = pc;

        stream.getTracks().forEach((track) => pc.addTrack(track, stream));

        const dc = pc.createDataChannel("oai-events");
        dataChannelRef.current = dc;

        dc.onmessage = (e: MessageEvent<string>) => {
          try {
            const msg = JSON.parse(e.data) as {
              type: string;
              delta?: string;
              transcript?: string;
            };

            if (
              msg.type ===
              "conversation.item.input_audio_transcription.delta"
            ) {
              if (msg.delta) {
                setInterim((prev) => {
                  const next = prev + msg.delta;
                  interimRef.current = next;
                  return next;
                });
              }
            }

            if (
              msg.type ===
              "conversation.item.input_audio_transcription.completed"
            ) {
              const text = msg.transcript?.trim();
              if (text && callbackRef.current) {
                callbackRef.current(text + " ");
              }
              interimRef.current = "";
              setInterim("");
            }
          } catch {
            // ignore non-JSON
          }
        };

        dc.onopen = () => {
          listeningReachedRef.current = true;
          setState("listening");
          const { language: lang, transcriptionPrompt: prompt } =
            optionsRef.current;
          const sessionUpdate = {
            type: "session.update",
            session: {
              type: "realtime",
              audio: {
                input: {
                  transcription: {
                    model: "gpt-4o-mini-transcribe",
                    language: lang,
                    prompt,
                  },
                  turn_detection: {
                    type: "server_vad",
                    threshold: 0.5,
                    prefix_padding_ms: 300,
                    silence_duration_ms: 400,
                  },
                },
              },
            },
          };
          dc.send(JSON.stringify(sessionUpdate));
        };

        pc.onconnectionstatechange = () => {
          const st = pc.connectionState;
          if (st === "failed" || st === "closed" || st === "disconnected") {
            if (drainingRef.current) {
              finishDrainAndClose();
              return;
            }
            if (activeRef.current) {
              cleanup();
            }
          }
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        if (!activeRef.current) {
          cleanup();
          return;
        }

        let sdpAnswer: string;
        try {
          const res = await fetch(o.sessionPath, {
            method: "POST",
            headers: buildAuthHeaders(),
            body: offer.sdp,
          });
          const textBody = await res.text();
          if (!res.ok) {
            let detail = res.statusText;
            if (textBody.trim()) {
              try {
                const j = JSON.parse(textBody) as { detail?: unknown };
                detail =
                  typeof j.detail === "string"
                    ? j.detail
                    : textBody.slice(0, 240);
              } catch {
                detail = textBody.slice(0, 240);
              }
            }
            if (res.status === 503) {
              setError(
                "Voice input requires OPENAI_API_KEY on the server (even if the agent uses another provider).",
              );
            } else if (res.status === 401) {
              setError("Sign in to use voice input.");
            } else {
              setError(detail || "Transcription session failed.");
            }
            cleanup();
            return;
          }
          sdpAnswer = textBody;
        } catch {
          setError("Could not reach the transcription service.");
          cleanup();
          return;
        }

        if (!activeRef.current) {
          cleanup();
          return;
        }

        await pc.setRemoteDescription({ type: "answer", sdp: sdpAnswer });
      })();
    },
    [cleanup, finishDrainAndClose],
  );

  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  return {
    state,
    interim,
    error,
    clearError,
    start,
    stop,
  };
}
