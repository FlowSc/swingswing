import type { ReactNode } from "react";

export function Shell({ children }: { children: ReactNode }) {
  return (
    <main className="page">
      <section className="hero">
        <div>
          <p className="eyebrow">KOSPI AUTOMATED SWING</p>
          <h1>스윙봇</h1>
        </div>
        <div className="hero-card">
          <strong>KIS OPEN API 기반</strong>
        </div>
      </section>
      {children}
    </main>
  );
}
