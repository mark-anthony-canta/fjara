"use client";
import { useEffect, useRef, useState } from "react";
import { readEvents } from "../lib/stream.mjs";

type Citation = { id: number; url: string; title: string; quote: string; crawled_at: string };
type Answer = { answer: string; status: "answered" | "insufficient_evidence"; citations: Citation[] };
type Turn = { id: string; question: string; language: "en" | "is"; result?: Answer; error?: string };
const starters = ["What are the VAT rates in Iceland?", "Can a foreign company reclaim VAT?", "Where do I register a company?"];

export default function Home() {
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState<"en" | "is">("en");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const controller = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns, busy]);

  async function ask(text: string, selectedLanguage = language) {
    const clean = text.trim();
    if (!clean || clean.length > 2000 || controller.current) return;
    const abort = new AbortController();
    controller.current = abort;
    const id = crypto.randomUUID();
    setTurns(t => [...t, { id, question: clean, language: selectedLanguage }]);
    setQuestion(""); setBusy(true); setProgress("Connecting to your sources…");
    let received = false;
    try {
      const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: clean, language: selectedLanguage }), signal: abort.signal });
      if (!response.ok || !response.body) {
        const problem = await response.json().catch(() => ({}));
        throw new Error(typeof problem.detail === "string" ? problem.detail : "Unable to answer. Please try again.");
      }
      await readEvents(response.body, (event: string, data: Answer & { message: string }) => {
        if (event === "status") setProgress(data.message);
        if (event === "answer") {
          received = true;
          setTurns(t => t.map(turn => turn.id === id ? { ...turn, result: data } : turn));
        }
      });
      if (!received) throw new Error("No answer was received. Please retry.");
    } catch (error) {
      const message = abort.signal.aborted ? "Request stopped. You can retry whenever you're ready." : error instanceof Error ? error.message : "Something went wrong. Please retry.";
      setTurns(t => t.map(turn => turn.id === id ? { ...turn, error: message } : turn));
    } finally {
      controller.current = null; setBusy(false); setProgress(""); input.current?.focus();
    }
  }

  function citationText(turn: Turn) {
    return turn.result!.answer.split(/(\[\d+\])/g).map((part, i) => {
      const number = /^\[(\d+)\]$/.exec(part);
      return number && turn.result!.citations.some(c => c.id === Number(number[1]))
        ? <a className="inline-citation" key={i} href={`#source-${turn.id}-${number[1]}`} aria-label={`Go to source ${number[1]}`}>{part}</a>
        : part;
    });
  }

  return <div className="shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Fjara home"><span className="brand-mark">f</span>fjara<span className="brand-dot">.</span></a>
      <div className="sidebar-label">YOUR KNOWLEDGE COMPANION</div>
      <button className="new-chat" disabled={busy || !turns.length} onClick={() => { setTurns([]); input.current?.focus(); }}><span>＋</span> New conversation</button>
      <div className="nav-item"><span>◌</span> Ask Fjara <span className="nav-arrow">↗</span></div>
      <div className="source-note"><span className="tiny-label">BUILT ON OFFICIAL SOURCES</span><h3>Answers with a paper trail.</h3><p>Explore Icelandic accounting and tax guidance from Skatturinn.</p><a href="https://www.skatturinn.is/english/" target="_blank" rel="noopener noreferrer">Visit the source ↗</a></div>
      <div className="sidebar-bottom"><span className="status-dot"/> Icelandic accounting · Local workspace</div>
    </aside>
    <main>
      <header><div className="breadcrumb">Workspace <span>/</span> <strong>Ask Fjara</strong></div><div className="header-tag">SOURCE-GROUNDED ANSWERS</div></header>
      <div className="chat-area">
        {!turns.length ? <section className="welcome">
          <div className="eyebrow"><span className="status-dot"/> A LITTLE CLARITY GOES A LONG WAY</div>
          <h1>Icelandic accounting.<br/><em>A clearer starting point.</em></h1>
          <p className="intro">From VAT to company registration, ask your question.<br className="desktop-break"/> Get a grounded answer, with the sources to explore further.</p>
          <div className="starter-grid">{starters.map((text, i) => <button key={text} onClick={() => { setQuestion(text); input.current?.focus(); }}><span className="starter-number">0{i + 1}</span><span>{text}</span><span className="starter-arrow">↗</span></button>)}</div>
          <div className="coverage"><span>IN THE KNOWLEDGE BASE</span><p>VAT <b>·</b> Contractors <b>·</b> Company registration <b>·</b> Tax returns</p></div>
        </section> : <section className="conversation" aria-label="Conversation">
          {turns.map(turn => <article className="turn" key={turn.id}>
            <div className="question-label">YOU</div><h2>{turn.question}</h2>
            {(turn.result || turn.error) && <div className="answer-card"><div className="answer-label"><span className="mini-mark">f</span> FJARA <span>{turn.result?.status === "answered" ? "Sources checked" : "Evidence first"}</span></div>
              {turn.result && <><div className="answer" lang={turn.language}>{citationText(turn)}</div>{turn.result.citations.length > 0 && <div className="citations"><h3>Explore the sources</h3>{turn.result.citations.map(c => <details id={`source-${turn.id}-${c.id}`} key={c.id}><summary><span className="source-index">{c.id}</span><span>{c.title}</span><span className="expand">＋</span></summary><blockquote>{c.quote}</blockquote><div className="source-meta"><span>Retrieved {new Date(c.crawled_at).toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" })}</span><a href={c.url} target="_blank" rel="noopener noreferrer">Open official source ↗</a></div></details>)}</div>}</>}
              {turn.error && <div className="error" role="alert"><p>{turn.error}</p><button disabled={busy} onClick={() => ask(turn.question, turn.language)}>Retry question ↗</button></div>}
            </div>}
          </article>)}
          {busy && <div className="progress" role="status"><span className="pulse"/>{progress}</div>}
          <div ref={end}/>
        </section>}
      </div>
      <div className="composer-wrap"><form className="composer" onSubmit={e => { e.preventDefault(); ask(question); }}>
        <label className="sr-only" htmlFor="question">Your accounting question</label>
        <textarea id="question" ref={input} value={question} maxLength={2000} disabled={busy} onChange={e => setQuestion(e.target.value)} placeholder="What would you like to understand?" rows={2} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(question); } }}/>
        <div className="composer-bottom"><label className="language">Answer in <select aria-label="Answer language" value={language} disabled={busy} onChange={e => setLanguage(e.target.value as "en" | "is")}><option value="en">English</option><option value="is">Íslenska</option></select></label><div className="send-group"><span className="count">{question.length}/2000</span>{busy ? <button className="send stop" type="button" onClick={() => controller.current?.abort()}>Stop ■</button> : <button className="send" type="submit" disabled={!question.trim()}>Ask Fjara <span>↑</span></button>}</div></div>
      </form><p className="footnote">Based on saved official guidance. Verify important decisions with a professional.<br/>Each question stands alone. Your conversation stays in this tab.</p></div>
    </main>
  </div>;
}
