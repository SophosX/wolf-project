// GET /api/export?status=angenommen&format=md|csv
// Markdown: komplette Skript-Pakete · CSV: Tabellen-Export (Semikolon, Excel-DE)

import { NextRequest, NextResponse } from "next/server";
import { holeVideos } from "@/lib/daten";
import { formatDatum } from "@/lib/format";
import { hookLabel, themaLabel } from "@/lib/typen";
import type { Status, Video } from "@/lib/typen";

export const dynamic = "force-dynamic";

function csvFeld(wert: unknown): string {
  const s = String(wert ?? "");
  return '"' + s.replace(/"/g, '""').replace(/\r?\n/g, " ") + '"';
}

function alsCsv(videos: Video[]): string {
  const kopf = [
    "id", "plattform", "titel", "kanal", "views", "score", "status",
    "thema", "falschaussage", "begruendung", "url", "veroeffentlicht",
  ];
  const zeilen = videos.map((v) =>
    [
      v.id, v.plattform, v.titel, v.kanal, v.views, v.score, v.status,
      v.claim?.thema || "", v.claim?.aussage || "", v.claim?.begruendung || "",
      v.url, v.veroeffentlicht,
    ].map(csvFeld).join(";")
  );
  // BOM für Excel-Umlaute
  return "﻿" + kopf.join(";") + "\n" + zeilen.join("\n") + "\n";
}

function alsMarkdown(videos: Video[], status: string): string {
  const teile: string[] = [
    "# Wolf Radar — Export (" + status + ")",
    "",
    "Exportiert am " + formatDatum(new Date().toISOString()) + " · " + videos.length + " Videos",
    "",
  ];
  for (const v of videos) {
    teile.push("---", "", "## " + v.titel);
    teile.push(
      "",
      "- **Plattform:** " + v.plattform,
      "- **Kanal:** " + v.kanal,
      "- **Views:** " + v.views.toLocaleString("de-DE"),
      "- **Score:** " + v.score + "/100",
      "- **Thema:** " + themaLabel(v.claim?.thema || ""),
      "- **Link:** " + v.url,
      "",
      "> **Falschaussage:** „" + (v.claim?.aussage || "") + "“",
      "",
      "**Warum falsch:** " + (v.claim?.begruendung || ""),
      ""
    );
    for (const s of v.skripte || []) {
      teile.push(
        "### Skript Variante " + s.variante + " — " + hookLabel(s.hook_typ),
        "",
        s.inhalt_md,
        ""
      );
      if (s.quellen?.length) {
        teile.push("**Quellen:**", "");
        for (const q of s.quellen) teile.push("- [" + q.titel + "](" + q.url + ")");
        teile.push("");
      }
    }
  }
  return teile.join("\n");
}

export async function GET(req: NextRequest) {
  try {
    const p = req.nextUrl.searchParams;
    const status = (p.get("status") || "angenommen") as Status;
    const format = p.get("format") === "csv" ? "csv" : "md";

    const videos = await holeVideos({ status });
    const datum = new Date().toISOString().slice(0, 10);

    if (format === "csv") {
      return new NextResponse(alsCsv(videos), {
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition":
            'attachment; filename="wolf-radar_' + status + "_" + datum + '.csv"',
        },
      });
    }
    return new NextResponse(alsMarkdown(videos, status), {
      headers: {
        "Content-Type": "text/markdown; charset=utf-8",
        "Content-Disposition":
          'attachment; filename="wolf-radar_' + status + "_" + datum + '.md"',
      },
    });
  } catch (e) {
    console.error("[api/export]", e);
    return NextResponse.json(
      { fehler: e instanceof Error ? e.message : "Export fehlgeschlagen" },
      { status: 500 }
    );
  }
}
