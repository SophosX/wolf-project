"use client";

// Rendert Markdown (Skripte, Faktenchecks) — Inhalte kommen aus eigener Pipeline/Gemini.

import { marked } from "marked";

export default function Markdown({ md }: { md: string }) {
  const html = (marked.parse(md || "", { async: false }) as string)
    // defensiv: keine Skripte/Event-Handler durchlassen
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/\son\w+="[^"]*"/gi, "");
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
