export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const timeout = AbortSignal.timeout(70000);
  try {
    const text = await request.text();
    if (text.length > 12000) return Response.json({ detail: "Question is too long." }, { status: 413 });
    let input;
    try { input = JSON.parse(text); } catch { return Response.json({ detail: "Invalid request." }, { status: 400 }); }
    const response = await fetch(`${process.env.BACKEND_URL || "http://127.0.0.1:8000"}/chat/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input), signal: AbortSignal.any([request.signal, timeout]), cache: "no-store",
    });
    if (!response.ok) return Response.json({ detail: response.status === 422 ? "Enter a question of 1–2,000 characters." : "The answer service is unavailable. Please try again." }, { status: response.status });
    return new Response(response.body, { headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no" } });
  } catch {
    return Response.json({ detail: "Couldn't connect to the answer service. Please try again." }, { status: 503 });
  }
}
