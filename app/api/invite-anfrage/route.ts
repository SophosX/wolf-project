// POST /api/invite-anfrage — öffentliches Formular der Landing:
// "Wer bist du und was willst du mit deinem Radar?" → invite_anfragen.
// Spam-Schutz: Honeypot-Feld + Mindestlänge + Tages-Dedupe je E-Mail.
// Best effort: ntfy-Push an den Betreiber bei neuer Anfrage.

import { NextRequest, NextResponse } from "next/server";
import { datenModus, supabaseAdmin } from "@/lib/daten";

export const dynamic = "force-dynamic";

async function ntfyPush(titel: string, text: string) {
  const url = process.env.NTFY_URL;
  if (!url) return;
  try {
    const headers: Record<string, string> = { Title: titel, Tags: "email,radar" };
    const auth = process.env.NTFY_AUTH;
    if (auth) headers.Authorization = "Basic " + Buffer.from(auth).toString("base64");
    await fetch(url, {
      method: "POST",
      headers,
      body: text,
      signal: AbortSignal.timeout(8000),
    });
  } catch (e) {
    console.error("[invite-anfrage] ntfy fehlgeschlagen:", e);
  }
}

export async function POST(req: NextRequest) {
  try {
    if (datenModus() !== "supabase") {
      return NextResponse.json({ fehler: "Nicht verfügbar." }, { status: 501 });
    }
    const body = await req.json().catch(() => ({}));

    // Honeypot: echte Menschen füllen "website" nicht aus
    if (String(body.website || "").trim() !== "") {
      return NextResponse.json({ ok: true }); // Bots still schlucken
    }
    const email = String(body.email || "").trim().toLowerCase().slice(0, 200);
    const name = String(body.name || "").trim().slice(0, 120);
    const kanal = String(body.kanal || "").trim().slice(0, 200);
    const nachricht = String(body.nachricht || "").trim().slice(0, 1500);
    if (!email.includes("@") || nachricht.length < 20) {
      return NextResponse.json(
        { fehler: "Bitte gültige E-Mail angeben und kurz beschreiben, wer du bist und was du vorhast (mind. 20 Zeichen)." },
        { status: 400 }
      );
    }

    const sb = await supabaseAdmin();
    // Dedupe: höchstens eine offene Anfrage pro E-Mail
    const { data: offen } = await sb
      .from("invite_anfragen")
      .select("id")
      .eq("email", email)
      .eq("status", "offen")
      .limit(1);
    if (offen && offen.length > 0) {
      return NextResponse.json({
        ok: true,
        hinweis: "Deine Anfrage ist schon bei uns — wir melden uns per E-Mail!",
      });
    }

    const { error } = await sb
      .from("invite_anfragen")
      .insert({ email, name: name || null, kanal: kanal || null, nachricht });
    if (error) throw new Error(error.message);

    ntfyPush(
      "📡 Neue Radar-Invite-Anfrage",
      (name || email) + (kanal ? " · " + kanal : "") + "\n" + nachricht.slice(0, 300)
    ).catch(() => {});

    return NextResponse.json({
      ok: true,
      hinweis: "Danke! Wir schauen uns deine Anfrage an und melden uns per E-Mail mit deinem Einladungs-Code.",
    });
  } catch (e) {
    console.error("[api/invite-anfrage]", e);
    return NextResponse.json({ fehler: "Anfrage konnte nicht gespeichert werden." }, { status: 500 });
  }
}
