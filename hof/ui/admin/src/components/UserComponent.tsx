import { useEffect, useRef, useState, useCallback } from "react";

interface UserComponentProps {
  componentName: string;
  props: Record<string, unknown>;
  onComplete: (data: Record<string, unknown>) => void;
}

export function UserComponent({ componentName, props, onComplete }: UserComponentProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [height, setHeight] = useState(400);
  const stableOnComplete = useCallback(onComplete, []);

  useEffect(() => {
    // #region agent log
    fetch('http://127.0.0.1:7345/ingest/403b2b0a-43ec-4bbc-b69d-a75588fe09bf',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'e035b7'},body:JSON.stringify({sessionId:'e035b7',location:'UserComponent.tsx:useEffect',message:'iframe_mounted',data:{componentName,iframeSrc:'/user-ui/',props},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    const handler = (event: MessageEvent) => {
      const { type, data, error } = event.data || {};

      // #region agent log
      fetch('http://127.0.0.1:7345/ingest/403b2b0a-43ec-4bbc-b69d-a75588fe09bf',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'e035b7'},body:JSON.stringify({sessionId:'e035b7',location:'UserComponent.tsx:handler',message:'postMessage_received',data:{type,hasData:!!data,hasError:!!error},timestamp:Date.now()})}).catch(()=>{});
      // #endregion
      switch (type) {
        case "hof:loaded":
          iframeRef.current?.contentWindow?.postMessage(
            { type: "hof:render", componentName, props },
            "*"
          );
          break;
        case "hof:ready":
          setStatus("ready");
          break;
        case "hof:complete":
          stableOnComplete(data);
          break;
        case "hof:error":
          console.error("User component error:", error);
          setStatus("error");
          break;
        case "hof:resize":
          if (event.data.height) setHeight(event.data.height);
          break;
      }
    };

    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [componentName, props, stableOnComplete]);

  return (
    <div>
      {status === "loading" && (
        <p style={{ color: "var(--text-secondary)", marginBottom: 8 }}>Loading component...</p>
      )}
      {status === "error" && (
        <div style={{ color: "var(--danger)" }}>
          <p>Component <code>{componentName}</code> failed to load.</p>
          <p style={{ fontSize: 12, marginTop: 4, color: "var(--text-secondary)" }}>
            Make sure <code>hof dev</code> is running and <code>ui/components/{componentName}.tsx</code> exists.
          </p>
        </div>
      )}
      <iframe
        ref={iframeRef}
        src="/user-ui/"
        style={{
          width: "100%",
          height,
          border: "none",
          borderRadius: 8,
          background: "#0f1117",
          display: status === "error" ? "none" : "block",
        }}
        title={`hof component: ${componentName}`}
      />
    </div>
  );
}
