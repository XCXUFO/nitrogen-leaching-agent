"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

// Web Speech is not included in TypeScript's DOM declarations yet.
interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onstart: (() => void) | null;
  onresult: ((event: { results: ArrayLike<RecognitionResult> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};
type Phase = "idle" | "starting" | "listening" | "stopping";

const errors: Record<string, string> = {
  "not-allowed": "请允许麦克风权限后重试。",
  "service-not-allowed": "语音服务不可用，请稍后重试或键盘输入。",
  "audio-capture": "未找到可用的麦克风，请检查设备。",
  "no-speech": "未听到语音，请重试。",
  network: "语音识别连接失败，请检查网络后重试。",
  "language-not-supported": "当前语音服务不支持普通话，请使用键盘输入。",
};

export function useSpeechInput(onTranscript: (text: string) => void, disabled?: boolean) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");
  const recognition = useRef<Recognition | null>(null);
  const stopTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const transcriptCallback = useRef(onTranscript);
  useLayoutEffect(() => { transcriptCallback.current = onTranscript; }, [onTranscript]);

  function release() {
    const current = recognition.current;
    recognition.current = null;
    if (stopTimer.current) clearTimeout(stopTimer.current);
    stopTimer.current = null;
    if (current) {
      current.onstart = current.onresult = current.onerror = current.onend = null;
      try { current.abort(); } catch { /* Already ended. */ }
    }
  }

  useEffect(() => {
    function cancel() {
      release();
      setPhase("idle");
      setInterim("");
    }
    function onVisibility() { if (document.hidden) cancel(); }
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", cancel);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", cancel);
      // Includes conversation switches, navigation and the form becoming busy.
      cancel();
    };
  }, [disabled]);

  function toggle() {
    const current = recognition.current;
    if (current) {
      if (phase === "stopping") return;
      if (phase === "starting") {
        release(); setPhase("idle"); setInterim("");
        return;
      }
      setPhase("stopping");
      // stop() keeps the final result, unlike abort(). Guard a missing end event.
      stopTimer.current = setTimeout(() => {
        if (recognition.current !== current) return;
        release(); setPhase("idle"); setInterim("");
        setError("语音识别超时，请重试。");
      }, 5000);
      try { current.stop(); } catch {
        release(); setPhase("idle"); setInterim("");
        setError("语音识别已中断，请重试。");
      }
      return;
    }
    if (disabled) return;
    setError("");
    if (!window.isSecureContext) {
      setError("请通过 HTTPS 或 localhost 使用语音输入。");
      return;
    }
    const speechWindow = window as SpeechWindow;
    const Constructor = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (!Constructor) {
      setError("当前浏览器不支持语音输入，请使用键盘输入。");
      return;
    }
    try {
      const instance = new Constructor();
      recognition.current = instance;
      instance.lang = "zh-CN";
      instance.continuous = true;
      instance.interimResults = true;
      const committed = new Set<number>();
      let receivedText = false;
      instance.onstart = () => {
        if (recognition.current === instance) setPhase("listening");
      };
      instance.onresult = (event) => {
        if (recognition.current !== instance) return;
        let finalText = "", preview = "";
        for (let i = 0; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) {
            if (!committed.has(i)) { finalText += result[0].transcript; committed.add(i); }
          } else preview += result[0].transcript;
        }
        if (finalText.trim()) {
          receivedText = true;
          transcriptCallback.current(finalText.trim());
        }
        setInterim(preview);
      };
      instance.onerror = (event) => {
        if (recognition.current !== instance) return;
        release(); setPhase("idle"); setInterim("");
        setError(errors[event.error] ?? "语音识别已中断，请重试。");
      };
      instance.onend = () => {
        if (recognition.current !== instance) return;
        release(); setPhase("idle"); setInterim("");
        if (!receivedText) setError("未识别到文字，请重试。");
      };
      setPhase("starting");
      setInterim("");
      instance.start();
    } catch (cause) {
      release(); setPhase("idle"); setInterim("");
      setError(cause instanceof DOMException && cause.name === "NotAllowedError"
        ? errors["not-allowed"] : "无法启动语音输入，请检查麦克风后重试。");
    }
  }

  return { active: phase !== "idle", phase, interim, error, toggle };
}
