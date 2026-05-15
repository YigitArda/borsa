"use client";

import { useState, ReactNode } from "react";

interface TooltipProps {
  children: ReactNode;
  text: string;
  position?: "top" | "bottom" | "left" | "right";
}

export default function Tooltip({ children, text, position = "top" }: TooltipProps) {
  const [show, setShow] = useState(false);

  const posStyle: Record<string, React.CSSProperties> = {
    top: { bottom: "100%", left: "50%", transform: "translateX(-50%)", marginBottom: "6px" },
    bottom: { top: "100%", left: "50%", transform: "translateX(-50%)", marginTop: "6px" },
    left: { right: "100%", top: "50%", transform: "translateY(-50%)", marginRight: "6px" },
    right: { left: "100%", top: "50%", transform: "translateY(-50%)", marginLeft: "6px" },
  };

  return (
    <span
      style={{ position: "relative", display: "inline-block" }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <span
          style={{
            position: "absolute",
            ...posStyle[position],
            background: "#ffffe0",
            color: "#000",
            border: "1px solid #cc9900",
            padding: "4px 8px",
            borderRadius: "3px",
            fontSize: "11px",
            fontFamily: "Tahoma,sans-serif",
            zIndex: 9999,
            boxShadow: "2px 2px 4px rgba(0,0,0,0.2)",
            maxWidth: "280px",
            whiteSpace: "normal",
            lineHeight: "1.4",
          }}
        >
          {text}
        </span>
      )}
    </span>
  );
}
